from __future__ import annotations

import argparse
import base64
import errno
import grp
import json
import os
import pwd
import shutil
import stat
import subprocess
import sys
from pathlib import Path


MAX_TEXT_FILE_BYTES = 1024 * 1024


class WorkerError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def drop_privileges(username: str) -> None:
    pw = pwd.getpwnam(username)
    os.environ["HOME"] = pw.pw_dir
    os.environ["USER"] = pw.pw_name
    os.environ["LOGNAME"] = pw.pw_name
    os.setgid(pw.pw_gid)
    os.initgroups(username, pw.pw_gid)
    os.setuid(pw.pw_uid)


def info(path: Path) -> dict:
    st = path.lstat()
    is_symlink = path.is_symlink()
    is_dir = path.is_dir()
    target = ""
    if is_symlink:
        try:
            resolved = path.resolve(strict=True)
            if resolved.is_relative_to(path.parent.resolve(strict=False)):
                target = str(resolved)
        except OSError:
            target = ""
    return {
        "name": path.name,
        "path": str(path),
        "type": "folder" if is_dir else path.suffix.lower().lstrip(".") or "file",
        "is_dir": is_dir,
        "size": st.st_size,
        "owner": pwd.getpwuid(st.st_uid).pw_name,
        "group": grp.getgrgid(st.st_gid).gr_name,
        "mode": stat.filemode(st.st_mode),
        "permissions": oct(stat.S_IMODE(st.st_mode)),
        "modified": st.st_mtime,
        "mtime": st.st_mtime,
        "mime": "directory" if is_dir else "file",
        "can_read": os.access(path, os.R_OK),
        "can_write": os.access(path, os.W_OK),
        "can_delete": os.access(path.parent, os.W_OK),
        "can_rename": os.access(path.parent, os.W_OK),
        "is_symlink": is_symlink,
        "target": target or None,
    }


def copy_any(src: Path, dst: Path) -> None:
    rsync = shutil.which("rsync")
    if not rsync:
        raise SystemExit("rsync is required for copy operations")
    subprocess.run([rsync, "--archive", "--protect-args", str(src), str(dst)], check=True, shell=False)


def move_any(src: Path, dst: Path) -> None:
    copy_any(src, dst)
    if src.is_dir() and not src.is_symlink():
        shutil.rmtree(src)
    else:
        src.unlink()


def fail_with_os_error(error: OSError) -> None:
    error_codes = {
        errno.EEXIST: "already_exists",
        errno.ENOENT: "not_found",
        errno.EACCES: "permission_denied",
        errno.EPERM: "permission_denied",
        errno.ENOSPC: "no_space",
        errno.EROFS: "read_only",
        errno.EISDIR: "is_directory",
        errno.ENOTDIR: "not_directory",
    }
    print(json.dumps({"error": error_codes.get(error.errno or 0, "operation_failed")}), file=sys.stderr)
    raise SystemExit(1)


def read_text_file(path: Path, max_bytes: int = MAX_TEXT_FILE_BYTES) -> dict:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        details = os.fstat(handle.fileno())
        if not stat.S_ISREG(details.st_mode):
            raise WorkerError("not_regular_file")
        if details.st_size > max_bytes:
            raise WorkerError("file_too_large")
        content = handle.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise WorkerError("file_too_large")
    if b"\x00" in content:
        raise WorkerError("binary_file")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkerError("binary_file") from exc
    return {
        "content": text,
        "encoding": "utf-8",
        "size": len(content),
        "mtime_ns": details.st_mtime_ns,
    }


def write_text_file(path: Path, content: str, expected_mtime_ns: int | None, max_bytes: int = MAX_TEXT_FILE_BYTES) -> dict:
    encoded = content.encode("utf-8")
    if len(encoded) > max_bytes:
        raise WorkerError("file_too_large")
    flags = os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "wb", buffering=0) as handle:
        details = os.fstat(handle.fileno())
        if not stat.S_ISREG(details.st_mode):
            raise WorkerError("not_regular_file")
        if expected_mtime_ns is not None and details.st_mtime_ns != expected_mtime_ns:
            raise WorkerError("changed_on_disk")
        handle.seek(0)
        handle.write(encoded)
        handle.truncate()
        os.fsync(handle.fileno())
        updated = os.fstat(handle.fileno())
    return {"ok": True, "encoding": "utf-8", "size": len(encoded), "mtime_ns": updated.st_mtime_ns}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--op", required=True)
    parser.add_argument("--payload", required=True)
    args = parser.parse_args()
    encoded_payload = sys.stdin.read() if args.payload == "-" else args.payload
    payload = json.loads(base64.b64decode(encoded_payload).decode("utf-8"))
    drop_privileges(args.user)

    op = args.op
    if op == "list":
        path = Path(payload["path"])
        print(json.dumps({
            "items": [info(child) for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))],
            "directory": info(path),
        }))
    elif op == "stat":
        print(json.dumps(info(Path(payload["path"]))))
    elif op == "mkdir":
        Path(payload["path"]).mkdir(parents=False, exist_ok=False)
        print(json.dumps({"ok": True}))
    elif op == "create":
        Path(payload["path"]).touch(exist_ok=False)
        print(json.dumps({"ok": True}))
    elif op == "copy":
        copy_any(Path(payload["src"]), Path(payload["dst"]))
        print(json.dumps({"ok": True}))
    elif op == "move":
        move_any(Path(payload["src"]), Path(payload["dst"]))
        print(json.dumps({"ok": True}))
    elif op == "rename":
        Path(payload["src"]).rename(payload["dst"])
        print(json.dumps({"ok": True}))
    elif op == "delete":
        path = Path(payload["path"])
        if not path.exists() and not path.is_symlink():
            print(json.dumps({"ok": True, "already_deleted": True}))
        elif path.is_dir():
            shutil.rmtree(path)
            print(json.dumps({"ok": True}))
        else:
            path.unlink()
            print(json.dumps({"ok": True}))
    elif op == "trash":
        path = Path(payload["path"])
        trash = Path.home() / ".local/share/Trash/files"
        trash.mkdir(parents=True, exist_ok=True)
        target = trash / path.name
        counter = 1
        while target.exists():
            target = trash / f"{path.stem}-{counter}{path.suffix}"
            counter += 1
        shutil.move(str(path), str(target))
        print(json.dumps({"ok": True, "target": str(target)}))
    elif op == "chmod":
        os.chmod(payload["path"], int(payload["mode"], 8))
        print(json.dumps({"ok": True}))
    elif op == "import_upload":
        src = Path(payload["tmp"])
        dst = Path(payload["dst"])
        with src.open("rb") as reader, dst.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
        print(json.dumps({"ok": True, "path": str(dst)}))
    elif op == "export_download":
        src = Path(payload["src"])
        tmp = Path(payload["tmp"])
        with src.open("rb") as reader, tmp.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
        print(json.dumps({"ok": True, "tmp": str(tmp)}))
    elif op == "preview":
        path = Path(payload["path"])
        limit = int(payload.get("limit", 1_048_576))
        data = path.read_bytes()[:limit]
        print(json.dumps({"content": base64.b64encode(data).decode("ascii")}))
    elif op == "read_text":
        print(json.dumps(read_text_file(Path(payload["path"]))))
    elif op == "write_text":
        print(json.dumps(write_text_file(Path(payload["path"]), payload["content"], payload.get("expected_mtime_ns"))))
    elif op == "search":
        root = Path(payload["path"])
        query = payload["query"].lower()
        results = []
        for item in root.rglob("*"):
            if query in item.name.lower():
                results.append(info(item))
                if len(results) >= 250:
                    break
        print(json.dumps(results))
    else:
        raise SystemExit(f"Unsupported operation: {op}")


if __name__ == "__main__":
    try:
        main()
    except WorkerError as error:
        print(json.dumps({"error": error.code}), file=sys.stderr)
        raise SystemExit(1) from None
    except OSError as error:
        fail_with_os_error(error)
