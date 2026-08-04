from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "verify_frontend_build.py"
spec = importlib.util.spec_from_file_location("verify_frontend_build", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def make_dist(root: Path) -> tuple[Path, Path]:
    dist = root / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    script = assets / "index-current123.js"
    script.write_text(
        'const endpoint="/api/modules/hosts-manager/enrollment-tokens";\n'
        'const contract="apmid_id";\n',
        encoding="utf-8",
    )
    (dist / "index.html").write_text(
        '<!doctype html><script type="module" src="/assets/index-current123.js"></script>\n',
        encoding="utf-8",
    )
    return dist, script


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        dist, tracked_script = make_dist(Path(temporary))
        module.verify(dist)

        manifest_path = dist / module.MANIFEST_NAME
        initial = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "assets/index-current123.js" in initial["files"]

        compatibility_asset = dist / "assets" / "index-previous456.js"
        compatibility_asset.write_text('console.log("previous");\n', encoding="utf-8")
        module.verify(dist)

        extended = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "assets/index-previous456.js" in extended["files"]

        tracked_script.write_text(
            'const endpoint="/api/modules/hosts-manager/enrollment-tokens";\n'
            'const contract="apmid_id";\n'
            'console.log("modified");\n',
            encoding="utf-8",
        )
        try:
            module.verify(dist)
        except ValueError as error:
            assert "changed after" in str(error)
        else:
            raise AssertionError("A modified tracked asset was not rejected")

    print("OK: additive compatibility assets pass; tracked-file modifications fail")


if __name__ == "__main__":
    main()
