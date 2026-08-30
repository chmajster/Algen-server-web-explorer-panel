from __future__ import annotations

import json

import pytest

from app.identity.models import Role
from app.identity.permissions import PERMISSION_REGISTRY, ROLE_PERMISSIONS
from app.modules.policy_as_code.engine import PolicyEngine
from app.modules.policy_as_code.models import PolicyDocument
from app.modules.policy_as_code.rbac import POLICY_EVALUATE, POLICY_MANAGE, POLICY_VIEW
from app.modules.policy_as_code.repository import PolicyConflictError, PolicyRepository, PolicyValidationError


YAML_POLICY = """\
apiVersion: webnas/v1
kind: PolicySet
metadata:
  name: linux-baseline
  description: Minimal Linux baseline
spec:
  enabled: true
  rules:
    - id: ssh.root-login
      severity: high
      message: Root SSH login must be disabled
      assert:
        path: ssh.permit_root_login
        operator: eq
        value: "no"
    - id: firewall.enabled
      severity: critical
      assert:
        all:
          - path: firewall.enabled
            operator: eq
            value: true
          - path: firewall.default_policy
            operator: in
            value: [drop, reject]
"""


def test_engine_evaluates_declarative_assertions():
    document = PolicyDocument.model_validate(__import__("yaml").safe_load(YAML_POLICY))
    result = PolicyEngine().evaluate(
        document,
        {"ssh": {"permit_root_login": "no"}, "firewall": {"enabled": True, "default_policy": "drop"}},
    )

    assert result["compliant"] is True
    assert result["score"] == 100
    assert result["passed"] == 2
    assert result["failed"] == 0
    assert result["results"][0]["evidence"][0]["path"] == "ssh.permit_root_login"


def test_engine_reports_failed_rule_without_executing_code():
    repository = PolicyRepository()
    malicious = YAML_POLICY.replace("operator: eq", "operator: python", 1)

    with pytest.raises(PolicyValidationError, match="unsupported assertion operator"):
        repository.parse(malicious, "yaml")


def test_repository_round_trip_and_format_switch(tmp_path):
    repository = PolicyRepository(tmp_path)
    created = repository.save(YAML_POLICY, "yaml", create=True)

    assert created.id == "linux-baseline"
    assert (tmp_path / "linux-baseline.yaml").exists()
    assert repository.summary() == {
        "total": 1,
        "enabled": 1,
        "disabled": 0,
        "invalid": 0,
        "rules": 2,
        "formats": {"yaml": 1, "json": 0},
    }

    payload = created.document.model_dump(mode="json", by_alias=True)
    payload["metadata"]["description"] = "JSON policy"
    updated = repository.save(json.dumps(payload), "json", expected_id="linux-baseline")

    assert updated.format == "json"
    assert not (tmp_path / "linux-baseline.yaml").exists()
    assert (tmp_path / "linux-baseline.json").exists()
    assert repository.get("linux-baseline").document.metadata.description == "JSON policy"


def test_repository_rejects_duplicate_and_renamed_update(tmp_path):
    repository = PolicyRepository(tmp_path)
    repository.save(YAML_POLICY, "yaml", create=True)

    with pytest.raises(PolicyConflictError):
        repository.save(YAML_POLICY, "yaml", create=True)

    renamed = YAML_POLICY.replace("name: linux-baseline", "name: other-baseline")
    with pytest.raises(PolicyValidationError, match="must match"):
        repository.save(renamed, "yaml", expected_id="linux-baseline")


def test_policy_permissions_follow_least_privilege_roles():
    assert {POLICY_VIEW, POLICY_EVALUATE, POLICY_MANAGE}.issubset(PERMISSION_REGISTRY)
    assert {POLICY_VIEW, POLICY_EVALUATE}.issubset(ROLE_PERMISSIONS[Role.operator])
    assert POLICY_MANAGE not in ROLE_PERMISSIONS[Role.operator]
    assert POLICY_VIEW in ROLE_PERMISSIONS[Role.auditor]
    assert POLICY_EVALUATE not in ROLE_PERMISSIONS[Role.auditor]
