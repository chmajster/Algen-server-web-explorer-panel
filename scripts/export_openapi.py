#!/usr/bin/env python3
"""Export the FastAPI OpenAPI contract without starting the application server.

The exporter deliberately uses an isolated temporary runtime configuration so
schema generation never writes to production paths such as /var/lib/webnas.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def isolated_config(root: Path) -> Path:
    """Create a complete config derived from the checked-in example.

    Only filesystem paths are rewritten. This keeps OpenAPI generation aligned
    with real application defaults while preventing import-time helpers from
    touching privileged host directories in CI or developer workstations.
    """

    data_dir = root / "data"
    log_dir = root / "logs"
    temp_dir = data_dir / "tmp"
    data_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    source = (ROOT / "config.example.yaml").read_text(encoding="utf-8")
    source = source.replace('data_dir: "/var/lib/webnas"', f'data_dir: "{data_dir}"')
    source = source.replace('log_dir: "/var/log/webnas"', f'log_dir: "{log_dir}"')
    source = source.replace('temp_dir: "/var/lib/webnas/tmp"', f'temp_dir: "{temp_dir}"')
    source = source.replace(
        'session_secret: "change-this-secret-during-install"',
        'session_secret: "openapi-export-only-not-a-runtime-secret"',
    )
    config = root / "config.yaml"
    config.write_text(source, encoding="utf-8")
    return config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="webnas-openapi-") as temporary:
        config = isolated_config(Path(temporary))
        os.environ["WEBNAS_CONFIG"] = str(config)

        # Import only after WEBNAS_CONFIG is isolated because some application
        # services construct persistent stores during module import.
        from app.bootstrap import create_app

        app = create_app(mount_frontend=False)
        contract = app.openapi()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
