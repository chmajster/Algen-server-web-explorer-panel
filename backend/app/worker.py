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
import time
from pathlib import Path
from typing import Any


MAX_TEXT_FILE_BYTES = 1024 * 1024
DEFAULT_SEARCH_LIMIT = 250
DEFAULT_SEARCH_MAX_ENTRIES = 100_000
DEFAULT_SEARCH_TIMEOUT_SECONDS = 15.0
FULL_METADATA_SORTS = {"size", "owner", "group", "permissions", "modified", "mtime"}


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


def _light_entry(entry: os.DirEntry[str]) -> dict[str, Any]:
    try:
        # Follow symlinks here to preserve the previous Path.is_dir() semantics.
        # On normal filesystems DirEntry can answer this from d_type without a stat.
        is_dir = entry.is_dir(follow_symlinks=True)
    except OSError:
        is_dir = Path(entry.path).is_dir()
    return {
        "name": entry.name,
        "path": entry.path,
        "type": "folder" if is_dir else Path(entry.name).suffix.lower().lstrip(".") or "file",
        "is_dir": is_dir,
    }


def _matches_filter(item: dict[str, Any], query: str | None) -> bool:
    if not query:
        return True
    needle = query.lower()
    name = str(item.get("name", ""))
    return (
        needle in name.lower()
        or needle in str(item.get("type", "")).lower()
        or needle in Path(name).suffix.lower().lstrip(".")
    )


def _sort_value(item: dict[str, Any], sort_field: str) -> tuple[int, float, str]:
    if sort_field in {"modified", "mtime"}:
        return (0, float(item.get("mtime") or item.get("modified") or 0), "")
    value = item.get(sort_field) or ""
    if isinstance(value, str):
        return (1, 0, value.lower())
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    return (1, 0, str(value))


def _sort_items(items: list[dict[str, Any]], sort_field: str | None, direction: str, folders_first: bool) -> None:
    reverse = direction == "desc"
    if sort_field:
        items.sort(key=lambda item: _sort_value(item, sort_field), reverse=reverse)
    else:
        # The legacy worker returned a deterministic folder/name ordering even
        # when the API did not request an explicit sort field.
        items.sort(key=lambda item: (not bool(item.get("is_dir")), str(item.get("name", "")).lower()))
    if folders_first:
        items.sort(key=lambda item: not bool(item.get("is_dir")))


def list_directory(payload: dict[str, Any]) -> dict[str, Any]:
    path = Path(payload["path"])
    paginate = bool(payload.get("paginate", False))

    if not paginate:
        with os.scandir(path) as scan:
            items = [info(Path(entry.path)) for entry in scan]
        items.sort(key=lambda item: (not bool(item.get("is_dir")), str(item.get("name", "")).lower()))
        return {"items": items, "directory": info(path)}

    sort_field = payload.get("sort")
    direction = str(payload.get("direction", "asc"))
    folders_first = bool(payload.get("folders_first", True))
    show_hidden = bool(payload.get("show_hidden", False))
    filter_text = payload.get("filter")
    page = max(1, int(payload.get("page", 1)))
    page_size = min(max(1, int(payload.get("page_size", 20))), 200)

    light_items: list[dict[str, Any]] = []
    with os.scandir(path) as scan:
        for entry in scan:
            if not show_hidden and entry.name.startswith("."):
                continue
            item = _light_entry(entry)
            if _matches_filter(item, filter_text):
                light_items.append(item)

    if sort_field in FULL_METADATA_SORTS:
        # Correct sorting by metadata requires metadata for every candidate.
        items = [info(Path(item["path"])) for item in light_items]
        _sort_items(items, str(sort_field), direction, folders_first)
        total_items = len(items)
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        page = min(page, total_pages)
        start = (page - 1) * page_size
        page_items = items[start : start + page_size]
        metadata_items = total_items
    else:
        # Name/type sorting can be completed using DirEntry data. Only the
        # selected page is expanded into full owner/group/permission metadata.
        _sort_items(light_items, str(sort_field) if sort_field else None, direction, folders_first)
        total_items = len(light_items)
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        page = min(page, total_pages)
        start = (page - 1) * page_size
        selected = light_items[start : start + page_size]
        page_items = [info(Path(item["path"])) for item in selected]
        metadata_items = len(page_items)

    return {
        "items": page_items,
        "directory": info(path),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": total_pages,
            # Internal diagnostic used by regression tests/benchmarks; it is
            # not exposed by the public File Manager API.
            "metadata_items": metadata_items,
        },
    }


def search_directory(payload: dict[str, Any]) -> list[dict[str, Any]]:
    root = Path(payload["path"])
    query = str(payload["query"]).lower()
    limit = min(max(1, int(payload.get("limit", DEFAULT_SEARCH_LIMIT))), DEFAULT_SEARCH_LIMIT)
    max_entries = min(max(1, int(payload.get("max_entries", DEFAULT_SEARCH_MAX_ENTRIES))), 1_000_000)
    timeout_seconds = min(max(0.1, float(payload.get("timeout_seconds", DEFAULT_SEARCH_TIMEOUT_SECONDS))), 60.0)
    deadline = time.monotonic() + timeout_seconds
    results: list[dict[str, Any]] = []
    stack = [root]
    scanned = 0

    while stack and len(results) < limit and scanned < max_entries:
        if time.monotonic() >= deadline:
            break
        directory = stack.pop()
        try:
            with os.scandir(directory) as scan:
                for entry in scan:
                    scanned += 1
                    if scanned > max_entries or time.monotonic() >= deadline:
                        break
                    path = Path(entry.path)
                    if query in entry.name.lower():
                        try:
                            results.append(info(path))
                        except OSError:
                            continue
                        if len(results) >= limit:
                            break
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(path)
                    except OSError:
                        continue
        except OSError:
            continue
    return results


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
        print(json.dumps(list_directory(payload)))
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
        print(json.dumps(search_directory(payload)))
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
