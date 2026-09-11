from __future__ import annotations

from pathlib import Path


def test_every_backend_python_source_compiles() -> None:
    app_root = Path(__file__).resolve().parents[1] / "app"
    sources = sorted(app_root.rglob("*.py"))

    assert sources, "backend/app contains no Python sources"
    failures: list[str] = []
    for path in sources:
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec", dont_inherit=True)
        except (OSError, SyntaxError, UnicodeError) as error:
            failures.append(f"{path.relative_to(app_root)}: {type(error).__name__}: {error}")

    assert not failures, "Backend Python syntax errors:\n" + "\n".join(failures)
