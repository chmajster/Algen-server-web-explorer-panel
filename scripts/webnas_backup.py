from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "backend"))

from app.appliance_backup import ARCHIVE_SUFFIX, ApplianceBackupService, BackupValidationError  # noqa: E402
from app.config import get_config  # noqa: E402


def _service(config: str | None) -> ApplianceBackupService:
    if config:
        os.environ["WEBNAS_CONFIG"] = str(Path(config).resolve())
    get_config.cache_clear()
    return ApplianceBackupService(get_config())


def _import_archive(service: ApplianceBackupService, path: Path) -> str:
    source = path.resolve(strict=True)
    if not source.name.endswith(ARCHIVE_SUFFIX):
        raise BackupValidationError(f"backup file must end with {ARCHIVE_SUFFIX}")
    destination = service.backup_root / source.name
    if source != destination.resolve(strict=False):
        temporary = destination.with_suffix(destination.suffix + ".importing")
        try:
            shutil.copy2(source, temporary)
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    service.validate(destination.name)
    return destination.name


def main() -> int:
    parser = argparse.ArgumentParser(description="Create, validate or restore a WebNAS appliance backup")
    parser.add_argument("--config", help="WebNAS config path; defaults to WEBNAS_CONFIG or /etc/webnas/config.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a checksummed appliance backup")
    create.add_argument("--label", default="manual")
    create.add_argument("--exclude-config", action="store_true")
    create.add_argument("--exclude-secrets", action="store_true")

    validate = subparsers.add_parser("validate", help="Validate a backup without modifying the installation")
    validate.add_argument("archive", type=Path)

    restore = subparsers.add_parser("restore", help="Validate or restore a backup")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--apply", action="store_true", help="Apply the restore; default is dry-run")
    restore.add_argument("--confirm", default="", help="Required for --apply: RESTORE <archive-name>")

    args = parser.parse_args()
    service = _service(args.config)

    try:
        if args.command == "create":
            result = service.create(
                label=args.label,
                include_config=not args.exclude_config,
                include_secrets=not args.exclude_secrets,
            )
        elif args.command == "validate":
            archive_name = _import_archive(service, args.archive)
            result = {"archive": archive_name, **service.validate(archive_name)}
        else:
            archive_name = _import_archive(service, args.archive)
            if args.apply:
                expected = f"RESTORE {archive_name}"
                if args.confirm != expected:
                    parser.error(f"--apply requires --confirm {expected!r}")
            result = service.restore(archive_name, apply=args.apply)
    except (BackupValidationError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
