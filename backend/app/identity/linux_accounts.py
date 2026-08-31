from __future__ import annotations

import grp
import os
import pwd
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from ..audit import logger
from ..config import get_config
from ..package_center.executor import redact
from ..privileged_broker.runtime import broker_command, broker_required
from ..proxmox_guard import assert_admin_group_allowed, assert_admin_user_allowed
from .exceptions import identity_error
from .models import IDENTITY_NAME_RE, GroupCreateRequest, UserCreateRequest, UserPatchRequest, UserQuotaRequest


PROTECTED_USERS = {"root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail", "news", "uucp", "proxy", "www-data", "backup", "nobody", "systemd-network", "systemd-resolve", "messagebus", "pve", "pvedaemon", "pveproxy"}
PROTECTED_GROUPS = {"root", "sudo", "wheel", "shadow", "adm", "daemon", "www-data", "backup", "pve", "pveadmin", "pveproxy", "pve-cluster"}
ADMIN_GROUPS = {"sudo", "wheel"}
_account_lock = threading.RLock()


def validate_name(value: str, kind: str) -> str:
    if not IDENTITY_NAME_RE.fullmatch(value) or "/" in value or ".." in value or any(ord(char) < 32 for char in value):
        identity_error(400, f"INVALID_{kind.upper()}NAME", f"Invalid local {kind} name", field=f"{kind}name")
    return value


def validate_password(value: str) -> str:
    if not value or len(value) > 1024 or any(char in value for char in "\r\n:\x00"):
        identity_error(400, "INVALID_PASSWORD", "Password contains unsupported characters", field="password")
    return value


def validate_gecos(value: str) -> str:
    if len(value) > 256 or ":" in value or any(ord(char) < 32 for char in value):
        identity_error(400, "INVALID_GECOS", "Description contains unsupported characters", field="gecos")
    return value


def allowed_shells() -> list[str]:
    path = Path("/etc/shells")
    values: list[str] = []
    try:
        values = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip().startswith("/") and not line.strip().startswith("#")]
    except OSError:
        pass
    return sorted(set(values or ["/bin/bash", "/bin/sh", "/usr/bin/bash"]))


def validate_shell(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in allowed_shells():
        identity_error(400, "SHELL_NOT_ALLOWED", "Shell must be listed in /etc/shells", field="shell")
    return value


def validate_home(value: str | None, username: str) -> str | None:
    if value is None:
        return None
    if len(value) > 512 or any(ord(char) < 32 for char in value) or ".." in Path(value).parts:
        identity_error(400, "INVALID_HOME", "Invalid home directory", field="home")
    path = Path(value)
    if not path.is_absolute():
        identity_error(400, "INVALID_HOME", "Home directory must be absolute", field="home")
    allowed = (Path("/home"), Path("/srv/home"), Path("/srv/users"))
    resolved = path.resolve(strict=False)
    if resolved.name != username or not any(resolved == root / username or root in resolved.parents for root in allowed):
        identity_error(400, "HOME_OUTSIDE_ALLOWED_ROOT", "Home directory must be below /home, /srv/home, or /srv/users", field="home")
    return str(resolved)


def _tool(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        identity_error(503, "SYSTEM_TOOL_MISSING", f"Required system tool is missing: {name}")
    return executable


def _local_run(args: list[str], *, input_text: str | None = None, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
        env={"PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
    )


def _run(args: list[str], *, input_text: str | None = None, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    if broker_required():
        result = broker_command(args, input_text=input_text, timeout=timeout, actor="identity")
        if result is None:
            identity_error(503, "PRIVILEGED_BROKER_OPERATION_UNSUPPORTED", "Privileged broker does not support this Linux account operation")
    else:
        result = _local_run(args, input_text=input_text, timeout=timeout)
    if result.returncode != 0:
        identity_error(400, "LINUX_ACCOUNT_OPERATION_FAILED", redact(result.stderr.strip() or "Linux account operation failed"))
    return result


def _run_status(args: list[str], *, timeout: int = 5) -> subprocess.CompletedProcess[str] | None:
    if broker_required():
        return broker_command(args, timeout=timeout, actor="identity")
    return _local_run(args, timeout=timeout)


def local_user(username: str) -> pwd.struct_passwd:
    validate_name(username, "user")
    try:
        return pwd.getpwnam(username)
    except KeyError:
        identity_error(404, "LOCAL_USER_NOT_FOUND", "Local Linux user does not exist", field="username")


def local_group(groupname: str) -> grp.struct_group:
    validate_name(groupname, "group")
    try:
        return grp.getgrnam(groupname)
    except KeyError:
        identity_error(404, "LOCAL_GROUP_NOT_FOUND", "Local Linux group does not exist", field="groupname")


def groups_for(username: str) -> list[str]:
    account = local_user(username)
    groups = {item.gr_name for item in grp.getgrall() if username in item.gr_mem or item.gr_gid == account.pw_gid}
    try:
        groups.add(grp.getgrgid(account.pw_gid).gr_name)
    except KeyError:
        pass
    return sorted(groups)


def is_linux_admin(username: str) -> bool:
    try:
        account = pwd.getpwnam(username)
    except KeyError:
        return False
    if account.pw_uid == 0:
        return True
    return bool(set(groups_for(username)) & ADMIN_GROUPS)


def is_protected_user(username: str, uid: int | None = None) -> bool:
    if username in PROTECTED_USERS or username.startswith(("pve", "systemd-")):
        return True
    if uid is not None and uid < get_config().security.system_uid_threshold:
        return True
    return is_linux_admin(username)


def is_protected_group(groupname: str, gid: int | None = None) -> bool:
    if groupname in PROTECTED_GROUPS or groupname.startswith(("pve", "systemd-")):
        return True
    return gid is not None and gid < get_config().security.system_uid_threshold


def assert_manageable_user(username: str, action: str) -> pwd.struct_passwd:
    account = local_user(username)
    if is_protected_user(username, account.pw_uid):
        identity_error(403, "PROTECTED_LINUX_ACCOUNT", "This Linux account cannot be modified from WebNAS")
    assert_admin_user_allowed(username, account.pw_uid, action)
    return account


def assert_manageable_group(groupname: str, action: str) -> grp.struct_group:
    group = local_group(groupname)
    if is_protected_group(groupname, group.gr_gid):
        identity_error(403, "PROTECTED_LINUX_GROUP", "This Linux group cannot be modified from WebNAS")
    assert_admin_group_allowed(groupname, action)
    return group


def _account_status(username: str) -> tuple[bool, bool]:
    passwd = shutil.which("passwd")
    if not passwd:
        return False, False
    result = _run_status([passwd, "-S", username])
    fields = result.stdout.split() if result is not None and result.returncode == 0 else []
    locked = len(fields) > 1 and fields[1] in {"L", "LK"}
    chage = shutil.which("chage")
    required = False
    if chage:
        expiry = _run_status([chage, "-l", username])
        if expiry is not None and expiry.returncode == 0:
            required = "password must be changed" in expiry.stdout.casefold()
    return locked, required


def user_record(username: str) -> dict[str, Any]:
    account = local_user(username)
    groups = groups_for(username)
    try:
        primary_group = grp.getgrgid(account.pw_gid).gr_name
    except KeyError:
        primary_group = str(account.pw_gid)
    locked, password_change_required = _account_status(username)
    linux_admin = is_linux_admin(username)
    system = account.pw_uid < get_config().security.system_uid_threshold
    return {
        "username": account.pw_name, "uid": account.pw_uid, "gid": account.pw_gid, "primary_group": primary_group,
        "supplementary_groups": [group for group in groups if group != primary_group], "groups": groups,
        "home": account.pw_dir, "shell": account.pw_shell, "gecos": account.pw_gecos,
        "locked": locked, "password_change_required": password_change_required, "is_system": system,
        "linux_admin": linux_admin, "manageable": not is_protected_user(username, account.pw_uid),
    }


def list_users(*, include_system: bool = False, search: str = "") -> list[dict[str, Any]]:
    needle = search.casefold().strip()
    users = []
    for account in pwd.getpwall():
        if not include_system and account.pw_uid < get_config().security.system_uid_threshold:
            continue
        if needle and needle not in account.pw_name.casefold() and needle not in account.pw_gecos.casefold():
            continue
        users.append(user_record(account.pw_name))
    return sorted(users, key=lambda item: (item["is_system"], item["username"]))


def group_record(groupname: str) -> dict[str, Any]:
    group = local_group(groupname)
    primary_users = sorted(item.pw_name for item in pwd.getpwall() if item.pw_gid == group.gr_gid)
    supplementary = sorted(set(group.gr_mem) - set(primary_users))
    return {"name": group.gr_name, "groupname": group.gr_name, "gid": group.gr_gid, "primary_users": primary_users, "supplementary_members": supplementary, "members": sorted(set(primary_users) | set(group.gr_mem)), "is_system": group.gr_gid < get_config().security.system_uid_threshold, "protected": is_protected_group(group.gr_name, group.gr_gid), "manageable": not is_protected_group(group.gr_name, group.gr_gid)}


def list_groups(*, include_system: bool = False, search: str = "") -> list[dict[str, Any]]:
    needle = search.casefold().strip()
    groups = []
    for group in grp.getgrall():
        if not include_system and group.gr_gid < get_config().security.system_uid_threshold:
            continue
        if needle and needle not in group.gr_name.casefold():
            continue
        groups.append(group_record(group.gr_name))
    return sorted(groups, key=lambda item: (item["is_system"], item["name"]))


def _validated_groups(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        group = assert_manageable_group(validate_name(value, "group"), "membership")
        if group.gr_name not in result:
            result.append(group.gr_name)
    return result


def create_user(payload: UserCreateRequest) -> None:
    username = validate_name(payload.username, "user")
    try:
        pwd.getpwnam(username)
    except KeyError:
        pass
    else:
        identity_error(409, "LOCAL_USER_EXISTS", "Local Linux user already exists", field="username")
    if payload.system:
        identity_error(400, "SYSTEM_USER_CREATION_BLOCKED", "Creating system users from WebNAS is not allowed")
    assert_admin_user_allowed(username, payload.uid, "create")
    shell = validate_shell(payload.shell)
    home = validate_home(payload.home, username)
    groups = _validated_groups(payload.groups)
    args = [_tool("useradd")]
    if payload.gid is None:
        args.append("--user-group")
    else:
        if payload.gid < get_config().security.system_uid_threshold:
            identity_error(400, "SYSTEM_GID_BLOCKED", "GID is below the system group threshold", field="gid")
        try:
            primary_group = grp.getgrgid(payload.gid)
        except KeyError:
            identity_error(400, "PRIMARY_GID_NOT_FOUND", "Primary GID does not identify a local group", field="gid")
        if is_protected_group(primary_group.gr_name, primary_group.gr_gid):
            identity_error(403, "PROTECTED_LINUX_GROUP", "Protected Linux groups cannot be selected as a primary group", field="gid")
        args.extend(["--gid", str(payload.gid)])
    if payload.create_home:
        args.append("--create-home")
    if home:
        args.extend(["--home-dir", home])
    if shell:
        args.extend(["--shell", shell])
    if payload.gecos:
        args.extend(["--comment", validate_gecos(payload.gecos)])
    if groups:
        args.extend(["--groups", ",".join(groups)])
    if payload.uid is not None:
        if payload.uid < get_config().security.system_uid_threshold:
            identity_error(400, "SYSTEM_UID_BLOCKED", "UID is below the system account threshold", field="uid")
        args.extend(["--uid", str(payload.uid)])
    with _account_lock:
        _run([*args, username])
        try:
            _run([_tool("chpasswd")], input_text=f"{username}:{validate_password(payload.password)}\n")
            if payload.force_password_change:
                _run([_tool("chage"), "-d", "0", username])
        except Exception:
            try:
                _run([_tool("userdel"), "--remove", username])
            except Exception as cleanup_error:
                logger.error("identity_user_create_rollback_failed user=%s error=%s", username, type(cleanup_error).__name__)
            raise


def update_user(username: str, payload: UserPatchRequest) -> str:
    account = assert_manageable_user(username, "update")
    next_username = validate_name(payload.new_username, "user") if payload.new_username else username
    args = [_tool("usermod")]
    if payload.new_username and payload.new_username != username:
        try:
            pwd.getpwnam(payload.new_username)
        except KeyError:
            args.extend(["--login", payload.new_username])
        else:
            identity_error(409, "LOCAL_USER_EXISTS", "Target local username already exists", field="new_username")
    if payload.home is not None:
        args.extend(["--home", validate_home(payload.home, next_username) or payload.home])
        if payload.move_home:
            args.append("--move-home")
    if payload.shell is not None:
        args.extend(["--shell", validate_shell(payload.shell) or payload.shell])
    if payload.gecos is not None:
        args.extend(["--comment", validate_gecos(payload.gecos)])
    additions = _validated_groups(payload.groups_add)
    if additions:
        args.extend(["--append", "--groups", ",".join(additions)])
    with _account_lock:
        if len(args) > 1:
            _run([*args, username])
        for group in _validated_groups(payload.groups_remove):
            _run([_tool("gpasswd"), "--delete", next_username, group])
        if payload.force_password_change is True:
            _run([_tool("chage"), "-d", "0", next_username])
        elif payload.force_password_change is False:
            _run([_tool("chage"), "-d", "-1", next_username])
    assert_admin_user_allowed(username, account.pw_uid, "update")
    return next_username


def delete_user(username: str, *, remove_home: bool) -> None:
    assert_manageable_user(username, "delete")
    args = [_tool("userdel")]
    if remove_home:
        args.append("--remove")
    with _account_lock:
        _run([*args, username])


def set_lock(username: str, locked: bool) -> None:
    assert_manageable_user(username, "lock" if locked else "unlock")
    with _account_lock:
        _run([_tool("usermod"), "--lock" if locked else "--unlock", username])


def change_password(username: str, password: str, force_change: bool) -> None:
    assert_manageable_user(username, "password")
    with _account_lock:
        _run([_tool("chpasswd")], input_text=f"{username}:{validate_password(password)}\n")
        if force_change:
            _run([_tool("chage"), "-d", "0", username])


def set_quota(username: str, payload: UserQuotaRequest) -> None:
    account = assert_manageable_user(username, "quota")
    hard = payload.hard_mb if payload.hard_mb is not None else payload.soft_mb
    if hard < payload.soft_mb:
        identity_error(400, "INVALID_QUOTA", "Hard quota cannot be lower than soft quota", field="hard_mb")
    mountpoint = payload.mountpoint or str(Path(account.pw_dir).anchor or "/")
    if not Path(mountpoint).is_absolute() or ".." in Path(mountpoint).parts:
        identity_error(400, "INVALID_MOUNTPOINT", "Quota mount point must be an absolute path", field="mountpoint")
    _run([_tool("setquota"), "-u", username, str(payload.soft_mb * 1024), str(hard * 1024), "0", "0", mountpoint])


def create_group(payload: GroupCreateRequest) -> None:
    name = validate_name(payload.groupname, "group")
    try:
        grp.getgrnam(name)
    except KeyError:
        pass
    else:
        identity_error(409, "LOCAL_GROUP_EXISTS", "Local Linux group already exists", field="groupname")
    if payload.system:
        identity_error(400, "SYSTEM_GROUP_CREATION_BLOCKED", "Creating system groups from WebNAS is not allowed")
    assert_admin_group_allowed(name, "create")
    args = [_tool("groupadd")]
    if payload.gid is not None:
        if payload.gid < get_config().security.system_uid_threshold:
            identity_error(400, "SYSTEM_GID_BLOCKED", "GID is below the system group threshold", field="gid")
        args.extend(["--gid", str(payload.gid)])
    with _account_lock:
        _run([*args, name])


def rename_group(groupname: str, new_name: str) -> None:
    assert_manageable_group(groupname, "update")
    validate_name(new_name, "group")
    try:
        grp.getgrnam(new_name)
    except KeyError:
        pass
    else:
        identity_error(409, "LOCAL_GROUP_EXISTS", "Target local group already exists", field="new_name")
    with _account_lock:
        _run([_tool("groupmod"), "--new-name", new_name, groupname])


def delete_group(groupname: str) -> None:
    record = group_record(groupname)
    assert_manageable_group(groupname, "delete")
    if record["primary_users"]:
        identity_error(409, "GROUP_IS_PRIMARY", "Group is the primary group of one or more users")
    with _account_lock:
        _run([_tool("groupdel"), groupname])


def set_group_member(groupname: str, username: str, present: bool) -> None:
    assert_manageable_group(groupname, "membership")
    assert_manageable_user(username, "update")
    with _account_lock:
        if present:
            _run([_tool("usermod"), "--append", "--groups", groupname, username])
        else:
            if local_user(username).pw_gid == local_group(groupname).gr_gid:
                identity_error(409, "PRIMARY_GROUP_MEMBERSHIP", "Primary group membership cannot be removed")
            _run([_tool("gpasswd"), "--delete", username, groupname])
