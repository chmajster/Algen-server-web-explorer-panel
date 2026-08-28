#!/usr/bin/env python3
"""Synchronize WebNAS project versions from the root VERSION file."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
PYTHON_VERSION_RE = re.compile(r'(?m)^__version__\s*=\s*"([^"]+)"\s*$')


class VersionError(RuntimeError):
    """Raised when version metadata is invalid or cannot be synchronized."""


def parse_version(value: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(value)
    if not match:
        raise VersionError(
            f"Invalid VERSION {value!r}; expected MAJOR.MINOR.PATCH without prefixes or prerelease metadata."
        )
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def read_version_file(root: Path) -> str:
    path = root / "VERSION"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise VersionError(f"Cannot read {path}: {error}") from error
    value = raw.strip()
    if not value or "\n" in value or "\r" in value:
        raise VersionError("VERSION must contain exactly one non-empty MAJOR.MINOR.PATCH line.")
    parse_version(value)
    return value


def project_version(text: str) -> str:
    section = re.search(r"(?ms)^\[project\]\s*$([\s\S]*?)(?=^\[|\Z)", text)
    if not section:
        raise VersionError("pyproject.toml is missing [project].")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', section.group(1))
    if not match:
        raise VersionError('pyproject.toml [project] is missing version = "...".')
    return match.group(1)


def set_project_version(text: str, version: str) -> str:
    section = re.search(r"(?ms)^\[project\]\s*$([\s\S]*?)(?=^\[|\Z)", text)
    if not section:
        raise VersionError("pyproject.toml is missing [project].")
    body = section.group(1)
    replaced, count = re.subn(
        r'(?m)^(version\s*=\s*")[^"]+("\s*)$',
        rf"\g<1>{version}\2",
        body,
        count=1,
    )
    if count != 1:
        raise VersionError('pyproject.toml [project] is missing version = "...".')
    return text[: section.start(1)] + replaced + text[section.end(1) :]


def python_version(text: str, label: str) -> str:
    match = PYTHON_VERSION_RE.search(text)
    if not match:
        raise VersionError(f'{label} is missing __version__ = "...".')
    return match.group(1)


def set_python_version(text: str, version: str, label: str) -> str:
    replaced, count = PYTHON_VERSION_RE.subn(f'__version__ = "{version}"', text, count=1)
    if count != 1:
        raise VersionError(f'{label} is missing __version__ = "...".')
    return replaced


def json_version(text: str, label: str) -> str:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise VersionError(f"{label} is not valid JSON: {error}") from error
    value = data.get("version") if isinstance(data, dict) else None
    if not isinstance(value, str):
        raise VersionError(f"{label} is missing a string top-level version.")
    return value


def set_json_version(text: str, version: str, label: str) -> str:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise VersionError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("version"), str):
        raise VersionError(f"{label} is missing a string top-level version.")
    data["version"] = version
    if label.endswith("package-lock.json"):
        packages = data.get("packages")
        root_package = packages.get("") if isinstance(packages, dict) else None
        if isinstance(root_package, dict) and isinstance(root_package.get("version"), str):
            root_package["version"] = version
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise VersionError(f"Cannot write {path}: {error}") from error


def load_targets(root: Path) -> list[tuple[Path, str, str]]:
    targets = [
        (root / "pyproject.toml", "pyproject", "pyproject.toml"),
        (root / "backend" / "app" / "__init__.py", "python", "backend/app/__init__.py"),
        (root / "frontend" / "package.json", "json", "frontend/package.json"),
    ]
    lock = root / "frontend" / "package-lock.json"
    if lock.exists():
        targets.append((lock, "json", "frontend/package-lock.json"))

    loaded: list[tuple[Path, str, str]] = []
    for path, kind, _label in targets:
        try:
            loaded.append((path, kind, path.read_text(encoding="utf-8")))
        except OSError as error:
            raise VersionError(f"Cannot read {path}: {error}") from error
    return loaded


def current_target_version(kind: str, content: str, label: str) -> str:
    if kind == "pyproject":
        return project_version(content)
    if kind == "python":
        return python_version(content, label)
    return json_version(content, label)


def synchronized_content(kind: str, content: str, version: str, label: str) -> str:
    if kind == "pyproject":
        return set_project_version(content, version)
    if kind == "python":
        return set_python_version(content, version, label)
    return set_json_version(content, version, label)


def bump_version(version: str, part: str) -> str:
    major, minor, patch = parse_version(version)
    if part == "patch":
        patch += 1
    elif part == "minor":
        minor += 1
        patch = 0
    elif part == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        raise VersionError(f"Unsupported bump type: {part}")
    return f"{major}.{minor}.{patch}"


def check_versions(root: Path, version: str, targets: list[tuple[Path, str, str]]) -> list[str]:
    mismatches: list[str] = []
    for path, kind, content in targets:
        label = str(path.relative_to(root))
        current = current_target_version(kind, content, label)
        if current != version:
            mismatches.append(f"{label}: {current} != VERSION {version}")
        if label == "frontend/package-lock.json":
            data = json.loads(content)
            packages = data.get("packages") if isinstance(data, dict) else None
            root_package = packages.get("") if isinstance(packages, dict) else None
            nested = root_package.get("version") if isinstance(root_package, dict) else None
            if isinstance(nested, str) and nested != version:
                mismatches.append(f"{label} packages[''].version: {nested} != VERSION {version}")
    return mismatches


def synchronize(root: Path, version: str, targets: list[tuple[Path, str, str]]) -> None:
    prepared: list[tuple[Path, str]] = []
    for path, kind, content in targets:
        label = str(path.relative_to(root))
        prepared.append((path, synchronized_content(kind, content, version, label)))
    for path, content in prepared:
        atomic_write(path, content)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Verify versions without modifying files.")
    mode.add_argument("--bump", choices=("patch", "minor", "major"), help="Bump VERSION and synchronize metadata.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        version = read_version_file(root)
        targets = load_targets(root)

        if args.check:
            mismatches = check_versions(root, version, targets)
            if mismatches:
                for mismatch in mismatches:
                    print(mismatch, file=sys.stderr)
                return 1
            print(f"Version check OK: {version}")
            return 0

        if args.bump:
            version = bump_version(version, args.bump)
            # Validate every target before changing VERSION so a malformed target
            # cannot leave the repository in a partially bumped state.
            for path, kind, content in targets:
                label = str(path.relative_to(root))
                current_target_version(kind, content, label)
                synchronized_content(kind, content, version, label)
            atomic_write(root / "VERSION", f"{version}\n")

        synchronize(root, version, targets)
        print(f"{'Bumped version' if args.bump else 'Version synchronized'}: {version}")
        return 0
    except VersionError as error:
        print(f"version error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
