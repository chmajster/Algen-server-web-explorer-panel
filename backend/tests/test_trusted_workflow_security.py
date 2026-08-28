from __future__ import annotations

from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
TRUSTED_WORKFLOW = REPOSITORY / ".github" / "workflows" / "trusted-self-hosted.yml"


def test_manual_production_deploy_requires_successful_hosted_ci_for_exact_main_sha() -> None:
    workflow = TRUSTED_WORKFLOW.read_text(encoding="utf-8")

    assert "actions: read" in workflow
    assert "Require successful hosted CI before manual production deployment" in workflow
    assert "github.event_name == 'workflow_dispatch' && inputs.deploy == true" in workflow
    assert "/actions/workflows/ci.yml/runs?" in workflow
    assert '"head_sha": target_sha' in workflow
    assert '"branch": "main"' in workflow
    assert '"event": "push"' in workflow
    assert '"status": "success"' in workflow
    assert 'run.get("head_sha") == target_sha' in workflow
    assert 'run.get("head_branch") == "main"' in workflow
    assert 'run.get("event") == "push"' in workflow
    assert 'run.get("conclusion") == "success"' in workflow
