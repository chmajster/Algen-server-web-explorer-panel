from __future__ import annotations

import argparse
import base64
import grp
import json
import os
import pwd
import shutil
import stat
import subprocess
from pathlib import Path


def drop_privileges(username: str) -> None:
    pw = pwd.getpwnam(username)
    os.setgid(pw.pw_gid)
    os.initgroups(username, pw.pw_gid)
    os.setuid(pw.pw_uid)


def info(path: Path) -> dict:
    st = path.lstat()
    return {
        "name": path.name,
        "path": str(path),
        "is_dir": path.is_dir(),
        "size": st.st_size,
        "owner": pwd.getpwuid(st.st_uid).pw_name,
        "group": grp.getgrgid(st.st_gid).gr_name,
        "mode": stat.filemode(st.st_mode),
        "permissions": oct(stat.S_IMODE(st.st_mode)),
        "modified": st.st_mtime,
        "mime": "directory" if path.is_dir() else "file",
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--op", required=True)
    parser.add_argument("--payload", required=True)
    args = parser.parse_args()
    payload = json.loads(base64.b64decode(args.payload).decode("utf-8"))
    drop_privileges(args.user)

    op = args.op
    if op == "list":
        path = Path(payload["path"])
        print(json.dumps([info(child) for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))]))
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
        if path.is_dir():
            shutil.rmtree(path)
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
    main()
