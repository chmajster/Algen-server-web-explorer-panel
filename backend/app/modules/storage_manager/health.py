from __future__ import annotations

from .service import service


def health_check() -> str:
    snapshot = service().snapshot()
    state = str(snapshot.get("state") or "unknown")
    issues = snapshot.get("issues")
    issue_count = len(issues) if isinstance(issues, list) else 0
    return f"{state}: {issue_count} storage issue(s)"
