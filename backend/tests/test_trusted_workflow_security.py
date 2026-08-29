from __future__ import annotations

from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
TRUSTED_WORKFLOW = REPOSITORY / ".github" / "workflows" / "trusted-self-hosted.yml"
CI_WORKFLOW = REPOSITORY / ".github" / "workflows" / "ci.yml"
DEPLOY_SCRIPT = REPOSITORY / "scripts" / "deploy_from_checkout.sh"


def test_manual_production_deploy_requires_successful_hosted_ci_for_exact_main_sha() -> None:
    workflow = TRUSTED_WORKFLOW.read_text(encoding="utf-8")

    assert "actions: read" in workflow
    assert "Resolve successful hosted CI artifact provenance" in workflow
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
    assert 'stream.write(f"run_id={run_id}\\n")' in workflow


def test_production_deploy_downloads_frontend_from_the_verified_ci_run() -> None:
    workflow = TRUSTED_WORKFLOW.read_text(encoding="utf-8")

    assert "ci_run_id: ${{ steps.resolve-ci-run.outputs.run_id }}" in workflow
    assert "uses: actions/download-artifact@v7" in workflow
    assert "name: frontend-dist" in workflow
    assert "github-token: ${{ github.token }}" in workflow
    assert "run-id: ${{ needs.trusted-integration.outputs.ci_run_id }}" in workflow
    assert 'test "$(tr -d \'\\r\\n\' < "${artifact}/.webnas-source-sha")" = "${TARGET_SHA}"' in workflow
    assert '"${GITHUB_WORKSPACE}/.trusted-artifacts/frontend-dist"' in workflow
    assert "FRONTEND_ARTIFACT_MANIFEST_SHA256" in workflow


def test_hosted_frontend_artifact_is_stamped_and_includes_hidden_integrity_files() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "Stamp frontend artifact provenance" in workflow
    assert 'printf \'%s\\n\' "${GITHUB_SHA}" > frontend/dist/.webnas-source-sha' in workflow
    assert "include-hidden-files: true" in workflow
    assert "name: frontend-dist" in workflow


def test_production_deploy_script_requires_tested_artifact_and_does_not_rebuild_frontend() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert 'FRONTEND_DIST="${3:?tested frontend artifact directory is required}"' in script
    assert ".webnas-assets.json" in script
    assert ".webnas-source-sha" in script
    assert '[[ "${ARTIFACT_SOURCE_SHA}" == "${SOURCE_SHA}" ]]' in script
    assert 'rsync -a --delete "${FRONTEND_DIST}/" "${RELEASE_DIR}/frontend/dist/"' in script
    assert "npm ci" not in script
    assert "npm run build" not in script
    assert ".webnas-frontend-manifest-sha256" in script
