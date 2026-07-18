from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import shlex
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal

import yaml

from .inventory import generate_inventory, validation_commands as inventory_validation_commands
from .playbooks import analyze_playbook, build_ansible_playbook_args, validation_commands as playbook_validation_commands
from .repository import AnsibleRepository
from .security import atomic_private_write, redact_text


LogCallback = Callable[[str, str], None]
ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]
SSHProbe = Literal["true", "os_release", "python", "sudo"]
SSH_COMMANDS: dict[SSHProbe, list[str]] = {
    "true": ["true"],
    "os_release": ["sh", "-c", "cat /etc/os-release 2>/dev/null || uname -a"],
    "python": ["sh", "-c", "command -v python3 || command -v python || true"],
    "sudo": ["sudo", "-n", "true"],
}
RECAP_RE = re.compile(
    r"^(?P<host>[^\s:]+)\s*:\s*ok=(?P<ok>\d+)\s+changed=(?P<changed>\d+)\s+unreachable=(?P<unreachable>\d+)\s+failed=(?P<failed>\d+)(?:\s+skipped=(?P<skipped>\d+))?(?:\s+rescued=(?P<rescued>\d+))?(?:\s+ignored=(?P<ignored>\d+))?"
)


class ControlledProcessCancelled(InterruptedError):
    def __init__(self, stdout: str, stderr: str) -> None:
        super().__init__("Ansible execution cancelled")
        self.stdout = stdout
        self.stderr = stderr


class ControlledProcessTimeout(RuntimeError):
    def __init__(self, timeout: int, stdout: str, stderr: str) -> None:
        super().__init__(f"Ansible execution timed out after {timeout} seconds")
        self.stdout = stdout
        self.stderr = stderr


def controller_identity() -> tuple[int, int, Path]:
    if os.name == "nt":
        return os.getuid() if hasattr(os, "getuid") else 1, os.getgid() if hasattr(os, "getgid") else 1, Path(tempfile.gettempdir()) / "webnas-ansible"
    import pwd

    entry = pwd.getpwnam("webnas-ansible")
    if entry.pw_uid == 0:
        raise RuntimeError("webnas-ansible must not be root")
    return entry.pw_uid, entry.pw_gid, Path(entry.pw_dir)


def demote_preexec(uid: int, gid: int) -> Callable[[], None]:
    if uid == 0 or gid == 0:
        raise ValueError("refusing to demote a playbook process to root")

    def demote() -> None:
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
        os.umask(0o077)

    return demote


def build_ssh_args(host: dict[str, Any], known_hosts: Path, *, key_file: Path | None = None, probe: SSHProbe = "true", batch_mode: bool = True) -> list[str]:
    address = str(host["address"])
    port = int(host.get("port") or 22)
    username = str(host.get("ssh_user") or "algen-ansible")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}", username) or not 1 <= port <= 65535:
        raise ValueError("invalid managed SSH target")
    args = [
        "ssh",
        "-T",
        "-p",
        str(port),
        "-o",
        f"BatchMode={'yes' if batch_mode else 'no'}",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ConnectionAttempts=1",
    ]
    if key_file:
        args.extend(["-i", str(key_file)])
    args.extend(["--", f"{username}@{address}", *SSH_COMMANDS[probe]])
    return args


def keyscan_args(address: str, port: int, executable: str = "ssh-keyscan") -> list[str]:
    if not 1 <= port <= 65535 or any(char in address for char in "\r\n\0"):
        raise ValueError("invalid SSH target")
    return [executable, "-T", "8", "-p", str(port), "-t", "ed25519,ecdsa,rsa", "--", address]


def fingerprint_key(public_key_line: str, executable: str = "ssh-keygen") -> str:
    result = subprocess.run([executable, "-lf", "-", "-E", "sha256"], input=public_key_line + "\n", capture_output=True, text=True, timeout=10, check=False, shell=False)
    if result.returncode != 0:
        raise RuntimeError("could not calculate SSH host fingerprint")
    fields = result.stdout.strip().split()
    if len(fields) < 2 or not fields[1].startswith("SHA256:"):
        raise RuntimeError("ssh-keygen returned an invalid fingerprint")
    return fields[1]


def parse_keyscan(output: str) -> list[dict[str, str]]:
    result = []
    for line in output.splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 3 or fields[1] not in {"ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521"}:
            continue
        result.append({"target": fields[0], "key_type": fields[1], "public_key": fields[2], "line": line})
    return result


def write_known_hosts(repository: AnsibleRepository, path: Path) -> None:
    keys = repository._list("known_host_keys", where="active=1 AND status='accepted'", order="address", limit=10_000)
    lines = []
    for item in keys:
        target = item["address"] if int(item["port"]) == 22 else f"[{item['address']}]:{item['port']}"
        lines.append(f"{target} {item['key_type']} {item['public_key']}")
    atomic_private_write(path, (("\n".join(lines) + "\n") if lines else "").encode())


@contextlib.contextmanager
def execution_directory(repository: AnsibleRepository, execution_id: str) -> Iterator[Path]:
    root = repository.root / "runs"
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    directory = Path(tempfile.mkdtemp(prefix=f"run-{execution_id[:12]}-", dir=root))
    os.chmod(directory, 0o700)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _safe_environment(home: Path, directory: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": str(home),
        "USER": "webnas-ansible",
        "LOGNAME": "webnas-ansible",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": str(directory),
        "ANSIBLE_CONFIG": str(directory / "ansible.cfg"),
        "ANSIBLE_LOCAL_TEMP": str(directory / "local-tmp"),
        "ANSIBLE_REMOTE_TEMP": ".ansible/tmp",
        "ANSIBLE_NOCOLOR": "1",
        "ANSIBLE_RETRY_FILES_ENABLED": "0",
        "ANSIBLE_HOST_KEY_CHECKING": "1",
        "ANSIBLE_ACTION_PLUGINS": "/usr/share/ansible/plugins/action",
        "ANSIBLE_CALLBACK_PLUGINS": "/usr/share/ansible/plugins/callback",
        "ANSIBLE_CONNECTION_PLUGINS": "/usr/share/ansible/plugins/connection",
        "ANSIBLE_LOOKUP_PLUGINS": "/usr/share/ansible/plugins/lookup",
    }


def _ansible_config(known_hosts: Path | None = None) -> str:
    ssh_args = ""
    if known_hosts is not None:
        ssh_args = f"ssh_args = -o UserKnownHostsFile={known_hosts} -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes\n"
    return (
        "[defaults]\n"
        "host_key_checking = True\n"
        "retry_files_enabled = False\n"
        "bin_ansible_callbacks = False\n"
        "interpreter_python = auto_silent\n"
        "[ssh_connection]\n"
        f"{ssh_args}"
        "pipelining = True\n"
    )


def _run_process(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    log: LogCallback,
    cancelled: CancelCallback,
    uid: int,
    gid: int,
) -> tuple[int, str, str]:
    if not args or not shutil.which(args[0]):
        raise RuntimeError(f"required executable is unavailable: {args[0] if args else 'unknown'}")
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    process = subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        shell=False,
        start_new_session=True,
        preexec_fn=demote_preexec(uid, gid) if os.name != "nt" else None,
    )

    def drain(stream: Any, name: str, output: list[str]) -> None:
        if stream is None:
            return
        for line in stream:
            safe = redact_text(line.rstrip())
            output.append(safe)
            log(name, safe)

    readers = [threading.Thread(target=drain, args=(process.stdout, "stdout", stdout_lines), daemon=True), threading.Thread(target=drain, args=(process.stderr, "stderr", stderr_lines), daemon=True)]
    for reader in readers:
        reader.start()
    deadline = time.monotonic() + timeout
    while process.poll() is None:
        if cancelled():
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGINT)
            else:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
            for reader in readers:
                reader.join(timeout=3)
            raise ControlledProcessCancelled("\n".join(stdout_lines), "\n".join(stderr_lines))
        if time.monotonic() >= deadline:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            for reader in readers:
                reader.join(timeout=3)
            raise ControlledProcessTimeout(timeout, "\n".join(stdout_lines), "\n".join(stderr_lines))
        time.sleep(0.2)
    for reader in readers:
        reader.join(timeout=3)
    return int(process.returncode or 0), "\n".join(stdout_lines), "\n".join(stderr_lines)


def _validation_files(repository: AnsibleRepository, directory: Path, files: dict[str, str]) -> tuple[int, int, Path]:
    uid, gid, home = controller_identity()
    atomic_private_write(directory / "ansible.cfg", _ansible_config().encode())
    for name, content in files.items():
        atomic_private_write(directory / name, content.encode())
    if os.name != "nt":
        os.chown(directory, uid, gid)
        for path in directory.iterdir():
            os.chown(path, uid, gid)
    return uid, gid, home


def validate_playbook_runtime(repository: AnsibleRepository, content: str) -> dict[str, Any]:
    """Run all ansible-core pre-flight checks as the isolated controller account."""
    with execution_directory(repository, "validate-playbook") as directory:
        inventory = yaml.safe_dump({"all": {"hosts": {"validation-target": {"ansible_host": "192.0.2.1"}}}})
        uid, gid, home = _validation_files(repository, directory, {"playbook.yml": content, "inventory.yml": inventory})
        results: list[dict[str, Any]] = []
        for args in playbook_validation_commands(directory / "playbook.yml", directory / "inventory.yml"):
            code, stdout, stderr = _run_process(
                args,
                cwd=directory,
                env=_safe_environment(home, directory),
                timeout=60,
                log=lambda _stream, _line: None,
                cancelled=lambda: False,
                uid=uid,
                gid=gid,
            )
            results.append({"check": args[-2], "ok": code == 0, "output": redact_text(stdout or stderr)[-4000:]})
            if code != 0:
                break
        return {"ok": len(results) == 4 and all(item["ok"] for item in results), "checks": results}


def validate_inventory_runtime(repository: AnsibleRepository, content: str, format_hint: str = "yaml") -> dict[str, Any]:
    """Run list and graph against a private inventory as the controller account."""
    with execution_directory(repository, "validate-inventory") as directory:
        filename = "inventory.ini" if format_hint == "ini" else "inventory.yml"
        uid, gid, home = _validation_files(repository, directory, {filename: content})
        results: list[dict[str, Any]] = []
        for args in inventory_validation_commands(str(directory / filename)):
            code, stdout, stderr = _run_process(
                args,
                cwd=directory,
                env=_safe_environment(home, directory),
                timeout=60,
                log=lambda _stream, _line: None,
                cancelled=lambda: False,
                uid=uid,
                gid=gid,
            )
            results.append({"check": args[-1], "ok": code == 0, "output": redact_text(stdout or stderr)[-4000:]})
            if code != 0:
                break
        return {"ok": len(results) == 2 and all(item["ok"] for item in results), "checks": results}


def parse_recap(stdout: str, host_map: dict[str, str] | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        match = RECAP_RE.match(line.strip())
        if not match:
            continue
        counts = {key: int(match.group(key) or 0) for key in ("ok", "changed", "unreachable", "failed", "skipped", "rescued", "ignored")}
        status = "failed" if counts["failed"] else "unreachable" if counts["unreachable"] else "changed" if counts["changed"] else "ok"
        host_name = match.group("host")
        result.append({"host_id": (host_map or {}).get(host_name), "host_name": host_name, "status": status, **counts})
    return result


def build_managed_user_script(username: str, public_key: str, sudo_profile: str = "none", sudoers_policy: str = "") -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}[a-z0-9_$]", username):
        raise ValueError("invalid managed Linux username")
    if not re.fullmatch(r"ssh-(?:ed25519|rsa) [A-Za-z0-9+/=]+(?: [^\r\n]{0,200})?", public_key.strip()):
        raise ValueError("invalid controller public key")
    policies = {
        "none": "",
        "password": f"{username} ALL=(ALL:ALL) ALL",
        "nopasswd": f"{username} ALL=(ALL:ALL) NOPASSWD: ALL",
        "custom": sudoers_policy,
    }
    if sudo_profile not in policies or (sudo_profile == "custom" and not sudoers_policy):
        raise ValueError("invalid sudo profile")
    quoted_user = shlex.quote(username)
    quoted_key = shlex.quote(public_key.strip())
    quoted_policy = shlex.quote(policies[sudo_profile])
    return f"""set -eu
managed_user={quoted_user}
public_key={quoted_key}
sudo_policy={quoted_policy}
created_user=0
sudoers_file=/etc/sudoers.d/$managed_user
rollback() {{
  rc=$?
  if [ "$rc" -ne 0 ]; then
    rm -f -- "$sudoers_file.new"
    if [ "$created_user" -eq 1 ]; then userdel -r -- "$managed_user" >/dev/null 2>&1 || true; fi
  fi
  exit "$rc"
}}
trap rollback EXIT HUP INT TERM
if ! id "$managed_user" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash -- "$managed_user"
  created_user=1
fi
home_dir=$(getent passwd "$managed_user" | cut -d: -f6)
test -n "$home_dir"
install -d -m 0700 -o "$managed_user" -g "$managed_user" -- "$home_dir/.ssh"
printf '%s\n' "$public_key" > "$home_dir/.ssh/authorized_keys.new"
chown "$managed_user:$managed_user" "$home_dir/.ssh/authorized_keys.new"
chmod 0600 "$home_dir/.ssh/authorized_keys.new"
mv -f -- "$home_dir/.ssh/authorized_keys.new" "$home_dir/.ssh/authorized_keys"
if [ -n "$sudo_policy" ]; then
  printf '%s\n' "$sudo_policy" > "$sudoers_file.new"
  chmod 0440 "$sudoers_file.new"
  visudo -cf "$sudoers_file.new"
  mv -f -- "$sudoers_file.new" "$sudoers_file"
fi
trap - EXIT HUP INT TERM
exit 0
"""


def run_remote_user_setup(
    repository: AnsibleRepository,
    host: dict[str, Any],
    credential_id: str,
    initial_username: str,
    managed_username: str,
    sudo_profile: str,
    sudoers_policy: str,
    log: LogCallback,
) -> None:
    credential = repository.credential_secret(credential_id)
    if credential["type"] not in {"ssh_private_key", "ssh_password"}:
        raise RuntimeError("remote account setup requires an SSH private-key or initial-password credential")
    public_key_path = repository.root / "home" / ".ssh" / "id_ed25519.pub"
    if not public_key_path.is_file():
        raise RuntimeError("controller public key is missing")
    script = build_managed_user_script(managed_username, public_key_path.read_text(encoding="utf-8").strip(), sudo_profile, sudoers_policy)
    with execution_directory(repository, "onboard") as directory:
        uid, gid, home = controller_identity()
        known_hosts = directory / "known_hosts"
        key_path = directory / "initial-key"
        write_known_hosts(repository, known_hosts)
        password_mode = credential["type"] == "ssh_password"
        if password_mode:
            password_path = directory / "initial-password"
            askpass_path = directory / "ssh-askpass"
            atomic_private_write(password_path, credential["secret"].encode())
            atomic_private_write(askpass_path, f"#!/bin/sh\nexec /bin/cat -- {shlex.quote(str(password_path))}\n".encode(), 0o700)
        else:
            atomic_private_write(key_path, credential["secret"].encode())
        private_paths = [directory, known_hosts, *( [password_path, askpass_path] if password_mode else [key_path] )]
        for path in private_paths:
            if os.name != "nt":
                os.chown(path, uid, gid)
        target = {**host, "ssh_user": initial_username}
        args = build_ssh_args(target, known_hosts, key_file=None if password_mode else key_path, probe="true", batch_mode=not password_mode)
        # Replace only the backend-owned fixed probe with a fixed sudo script receiver.
        args = args[: -len(SSH_COMMANDS["true"])] + (["sudo", "-S", "-p", "", "sh", "-s"] if password_mode else ["sudo", "-n", "sh", "-s"])
        environment = _safe_environment(home, directory)
        process_input = script
        if password_mode:
            environment.update({"SSH_ASKPASS": str(askpass_path), "SSH_ASKPASS_REQUIRE": "force", "DISPLAY": "webnas-ansible:0"})
            process_input = f"{credential['secret']}\n{script}"
        result = subprocess.run(
            args,
            input=process_input,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            shell=False,
            cwd=directory,
            env=environment,
            preexec_fn=demote_preexec(uid, gid) if os.name != "nt" else None,
        )
        log("stdout", redact_text(result.stdout, [credential["secret"]]))
        if result.returncode != 0:
            log("stderr", redact_text(result.stderr, [credential["secret"]]))
            raise RuntimeError("remote managed-user setup failed and rollback was requested")


def execute_ad_hoc(
    repository: AnsibleRepository,
    host_id: str,
    actor: str,
    log: LogCallback,
    progress: ProgressCallback,
    cancelled: CancelCallback,
    *,
    facts: bool = True,
) -> dict[str, Any]:
    host = repository.host(host_id)
    if not host:
        raise KeyError("host not found")
    known = repository.known_key(str(host["address"]), int(host["port"]))
    if not known:
        raise RuntimeError("SSH host key is not accepted")
    credential_id = str(host.get("credential_id") or "")
    if not credential_id:
        raise RuntimeError("host has no SSH credential")
    credential = repository.credential_secret(credential_id)
    if credential["type"] != "ssh_private_key":
        raise RuntimeError("Ansible host tests require a private SSH key credential")
    with execution_directory(repository, f"facts-{host_id}") as directory:
        uid, gid, home = controller_identity()
        inventory_path = directory / "inventory.yml"
        known_hosts = directory / "known_hosts"
        key_path = directory / "ssh-key"
        facts_dir = directory / "facts"
        facts_dir.mkdir(mode=0o700)
        inventory_text = generate_inventory([host], [], [])
        atomic_private_write(inventory_path, inventory_text.encode())
        atomic_private_write(key_path, credential["secret"].encode())
        write_known_hosts(repository, known_hosts)
        atomic_private_write(directory / "ansible.cfg", _ansible_config(known_hosts).encode())
        for path in (directory, facts_dir, inventory_path, known_hosts, key_path, directory / "ansible.cfg"):
            if os.name != "nt":
                os.chown(path, uid, gid)
        module = "ansible.builtin.setup" if facts else "ansible.builtin.ping"
        args = ["ansible", "--inventory", str(inventory_path), "--private-key", str(key_path), "--module-name", module]
        if facts:
            args.extend(["--tree", str(facts_dir)])
        args.extend(["--", str(host["name"])])
        progress(20, "Run controlled Ansible host test")
        code, stdout, stderr = _run_process(args, cwd=directory, env=_safe_environment(home, directory), timeout=120, log=log, cancelled=cancelled, uid=uid, gid=gid)
        now = time.time()
        with repository._lock, repository.connect() as connection:
            connection.execute("UPDATE hosts SET last_test_at=?,last_error=?,updated_at=?,updated_by=? WHERE id=?", (now, "" if code == 0 else redact_text(stderr)[:2000], now, actor, host_id))
        if code != 0:
            raise RuntimeError("Ansible host test failed")
        stored: dict[str, Any] = {}
        if facts:
            candidates = list(facts_dir.iterdir())
            if candidates:
                try:
                    raw = json.loads(candidates[0].read_text(encoding="utf-8"))
                    stored = raw.get("ansible_facts") if isinstance(raw, dict) and isinstance(raw.get("ansible_facts"), dict) else raw if isinstance(raw, dict) else {}
                except (OSError, ValueError):
                    stored = {}
            repository.save_facts(host_id, actor, stored)
        progress(100, "Host test and facts completed")
        return {"host_id": host_id, "ok": True, "facts_collected": bool(stored), "stdout": redact_text(stdout)}


def execute_template(repository: AnsibleRepository, execution_id: str, actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
    execution = repository.execution(execution_id)
    if not execution:
        raise KeyError("execution not found")
    template = repository._get("job_templates", str(execution["template_id"]))
    if not template:
        raise KeyError("job template not found")
    playbook = repository._get("playbooks", str(template["playbook_id"]))
    if not playbook:
        raise KeyError("playbook not found")
    preflight_content = str(execution.get("playbook_snapshot") or "") if execution.get("retry_of") else ""
    if not preflight_content:
        preflight_content = str(playbook["content"])
    analysis = analyze_playbook(preflight_content)
    if not analysis["ok"]:
        repository.update_execution(execution_id, actor, status="failed", stage="preflight_blocked", finished_at=time.time())
        raise RuntimeError("playbook is blocked by controller-local safety rules")
    try:
        runtime_validation = validate_playbook_runtime(repository, preflight_content)
    except Exception:
        repository.update_execution(execution_id, actor, status="failed", stage="preflight_failed", finished_at=time.time())
        raise
    if not runtime_validation["ok"]:
        repository.update_execution(execution_id, actor, status="failed", stage="preflight_failed", finished_at=time.time())
        raise RuntimeError("ansible-playbook pre-flight validation failed")
    hosts = [repository.host(host_id) for host_id in execution.get("host_ids", [])]
    hosts = [host for host in hosts if host and host.get("active")]
    groups = repository.list_groups()
    memberships = repository._list("host_group_memberships", limit=10_000, order="created_at")
    repository.acquire_execution_locks(
        execution_id,
        str(template["id"]),
        [str(host["id"]) for host in hosts],
        str(template.get("concurrency_policy") or "same_hosts"),
    )
    repository.update_execution(execution_id, actor, status="running", stage="prepare", started_at=time.time())
    try:
        with execution_directory(repository, execution_id) as directory:
            uid, gid, home = controller_identity()
            for child in (directory, directory / "local-tmp"):
                child.mkdir(parents=True, exist_ok=True)
                os.chmod(child, 0o700)
                if os.name != "nt":
                    os.chown(child, uid, gid)
            inventory_path = directory / "inventory.yml"
            playbook_path = directory / "playbook.yml"
            extra_vars_path = directory / "extra-vars.yml"
            known_hosts = directory / "known_hosts"
            config_path = directory / "ansible.cfg"
            inventory_text = str(execution.get("inventory_snapshot") or "") if execution.get("retry_of") else ""
            if not inventory_text:
                inventory_text = generate_inventory(hosts, groups, memberships)
            playbook_content = preflight_content
            for path, content in (
                (inventory_path, inventory_text),
                (playbook_path, playbook_content),
                (extra_vars_path, str(template.get("extra_vars") or "{}")),
                (config_path, _ansible_config(known_hosts)),
            ):
                atomic_private_write(path, content.encode())
                if os.name != "nt":
                    os.chown(path, uid, gid)
            write_known_hosts(repository, known_hosts)
            if os.name != "nt":
                os.chown(known_hosts, uid, gid)
            credentials_dir = directory / "credentials"
            credentials_dir.mkdir(mode=0o700)
            if os.name != "nt":
                os.chown(credentials_dir, uid, gid)
            env = _safe_environment(home, directory)
            ssh_credential = template.get("ssh_credential_id")
            if ssh_credential:
                credential = repository.credential_secret(str(ssh_credential))
                if credential["type"] == "ssh_private_key":
                    key_path = credentials_dir / "ssh_key"
                    atomic_private_write(key_path, credential["secret"].encode())
                    if os.name != "nt":
                        os.chown(key_path, uid, gid)
                    env["ANSIBLE_PRIVATE_KEY_FILE"] = str(key_path)
                else:
                    raise RuntimeError("playbook execution requires a private SSH key credential")
            become_credential = template.get("become_credential_id")
            vault_credential = template.get("vault_credential_id")
            secrets_payload: dict[str, str] = {}
            if become_credential:
                credential = repository.credential_secret(str(become_credential))
                if credential["type"] != "become_password":
                    raise RuntimeError("template become credential has the wrong type")
                secrets_payload["ansible_become_password"] = credential["secret"]
            if vault_credential:
                credential = repository.credential_secret(str(vault_credential))
                if credential["type"] != "vault_secret":
                    raise RuntimeError("template Vault credential has the wrong type")
                vault_path = credentials_dir / "vault-password"
                atomic_private_write(vault_path, credential["secret"].encode())
                if os.name != "nt":
                    os.chown(vault_path, uid, gid)
                env["ANSIBLE_VAULT_PASSWORD_FILE"] = str(vault_path)
            if secrets_payload:
                secret_vars_path = credentials_dir / "secret-vars.yml"
                ordinary_vars = yaml.safe_load(str(template.get("extra_vars") or "{}")) or {}
                if not isinstance(ordinary_vars, dict):
                    raise RuntimeError("template extra variables must be a mapping")
                atomic_private_write(secret_vars_path, yaml.safe_dump({**ordinary_vars, **secrets_payload}).encode())
                if os.name != "nt":
                    os.chown(secret_vars_path, uid, gid)
            else:
                secret_vars_path = None
            args = build_ansible_playbook_args(
                playbook_path,
                inventory_path,
                limit=str(template.get("limit_pattern") or ""),
                tags=list(template.get("tags") or []),
                skip_tags=list(template.get("skip_tags") or []),
                check=bool(template.get("check_mode")),
                diff=bool(template.get("diff_mode")),
                verbosity=int(template.get("verbosity") or 0),
                forks=int(template.get("forks") or 10),
                extra_vars_file=secret_vars_path or extra_vars_path,
            )
            progress(15, "Prepared private inventory and playbook snapshots")
            project = repository._get("projects", str(template.get("project_id") or ""))
            repository.update_execution(execution_id, actor, stage="running", inventory_snapshot=inventory_text, playbook_snapshot=playbook_content, project_commit=str(execution.get("project_commit") or (project or {}).get("last_commit") or ""))
            code, stdout, stderr = _run_process(args, cwd=directory, env=env, timeout=int(template.get("timeout_seconds") or 3600), log=log, cancelled=cancelled, uid=uid, gid=gid)
            progress(90, "Parse per-host Ansible recap")
            host_map = {str(host["name"]): str(host["id"]) for host in hosts}
            results = parse_recap(stdout, host_map)
            summary = {key: sum(int(item.get(key, 0)) for item in results) for key in ("ok", "changed", "failed", "unreachable", "skipped", "rescued", "ignored")}
            for result in results:
                repository.save_host_result(execution_id, actor, result)
            status = "completed" if code == 0 else "failed"
            repository.update_execution(execution_id, actor, status=status, stage="completed" if code == 0 else "failed", stdout=redact_text(stdout), stderr=redact_text(stderr), exit_code=code, summary_json=summary, finished_at=time.time())
            if code != 0:
                raise RuntimeError(f"ansible-playbook exited with code {code}")
            progress(100, "Ansible execution completed")
            return {"execution_id": execution_id, "summary": summary, "host_results": results, "exit_code": code}
    except InterruptedError as error:
        partial_stdout = redact_text(getattr(error, "stdout", ""))
        partial_stderr = redact_text(getattr(error, "stderr", ""))
        host_map = {str(host["name"]): str(host["id"]) for host in hosts}
        partial_results = parse_recap(partial_stdout, host_map)
        summary = {key: sum(int(item.get(key, 0)) for item in partial_results) for key in ("ok", "changed", "failed", "unreachable", "skipped", "rescued", "ignored")}
        for result in partial_results:
            repository.save_host_result(execution_id, actor, result)
        repository.update_execution(execution_id, actor, status="cancelled", stage="cancelled", stdout=partial_stdout, stderr=partial_stderr, summary_json=summary, finished_at=time.time())
        raise
    except Exception as error:
        captured_stdout = redact_text(getattr(error, "stdout", ""))
        captured_stderr = redact_text(getattr(error, "stderr", ""))
        values: dict[str, Any] = {"status": "failed", "stage": "failed", "finished_at": time.time()}
        if captured_stdout or captured_stderr:
            values.update({"stdout": captured_stdout, "stderr": captured_stderr})
        repository.update_execution(execution_id, actor, **values)
        raise
    finally:
        repository.release_host_locks(execution_id)
