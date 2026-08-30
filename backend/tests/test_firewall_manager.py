from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.firewall_manager.models import FirewallRuleInput
from app.modules.firewall_manager.service import FirewallService, parse_firewalld_rules, parse_nft_rules, parse_ufw_rules
from app.modules.firewall_manager.system import FirewallSystem
from app.privileged_broker.firewall_policy import dispatch
from app.privileged_broker.policy import CommandResult
from app.privileged_broker.protocol import BrokerRequest, Operation


def test_ufw_parser_normalizes_rule() -> None:
    rules = parse_ufw_rules("Status: active\n[ 1] 22/tcp ALLOW IN Anywhere # admin ssh\n")
    assert len(rules) == 1
    assert rules[0].id == "ufw:1"
    assert rules[0].port == "22"
    assert rules[0].protocol == "tcp"
    assert rules[0].action == "allow"


def test_firewalld_parser_keeps_opaque_id() -> None:
    rules = parse_firewalld_rules('rule family="ipv4" source address="10.0.0.0/8" port port="443" protocol="tcp" accept\n')
    assert len(rules) == 1
    assert rules[0].id.startswith("firewalld:")
    assert rules[0].port == "443"


def test_nft_parser_marks_only_webnas_rules_editable() -> None:
    payload = '{"nftables":[{"rule":{"family":"inet","table":"webnas","chain":"input","handle":5,"expr":[{"accept":null}]}}]}'
    rules = parse_nft_rules(payload)
    assert rules[0].editable is True
    assert rules[0].id == "nft:inet:webnas:input:5"


def test_rule_validation_rejects_bad_range() -> None:
    with pytest.raises(ValueError):
        FirewallRuleInput(protocol="tcp", port="70000")


def test_broker_rejects_arbitrary_firewall_command() -> None:
    request = BrokerRequest(request_id="a" * 32, actor="tester", operation=Operation.FIREWALL, payload={"backend": "nftables", "args": ["delete", "table", "inet", "filter"]})
    response = dispatch(request, runner=lambda _args, _stdin, _timeout: CommandResult(0, "", ""))
    assert response.ok is False
    assert response.error_code == "POLICY_DENIED"


def test_plan_flags_ssh_lockout(tmp_path: Path) -> None:
    class FakeSystem(FirewallSystem):
        def detect(self):
            from app.modules.firewall_manager.models import FirewallBackend
            return FirewallBackend.ufw, [FirewallBackend.ufw]
    svc = FirewallService(system=FakeSystem(), root=tmp_path)
    plan = svc.plan("rule.create", rule=FirewallRuleInput(action="drop", protocol="tcp", port="22"), client_ip="10.0.0.2", webnas_port=8080)
    assert plan["high_risk"] is True
    assert any("SSH" in warning for warning in plan["warnings"])


def test_ufw_parser_preserves_ipv6_port() -> None:
    rules = parse_ufw_rules("Status: active\n[ 2] 22/tcp (v6) ALLOW IN Anywhere (v6)\n")
    assert len(rules) == 1
    assert rules[0].port == "22"
    assert rules[0].protocol == "tcp"
    assert rules[0].family == "ipv6"


def test_firewalld_parser_does_not_treat_destination_as_source() -> None:
    rules = parse_firewalld_rules('rule family="ipv4" destination address="10.0.0.0/8" drop\n')
    assert rules[0].source == "any"
    assert rules[0].destination == "10.0.0.0/8"


def test_firewalld_family_any_is_not_forced_to_ipv4(tmp_path: Path) -> None:
    service = FirewallService(root=tmp_path)
    rich = service._firewalld_rich(FirewallRuleInput(action="drop", protocol="tcp", port="22", family="any"))
    assert 'family=' not in rich


def test_nft_parser_preserves_supported_match_predicates() -> None:
    payload = '{"nftables":[{"rule":{"family":"inet","table":"webnas","chain":"input","handle":5,"expr":[{"match":{"op":"==","left":{"payload":{"protocol":"tcp","field":"dport"}},"right":22}},{"accept":null}]}}]}'
    rule = parse_nft_rules(payload)[0]
    assert rule.editable is True
    assert rule.protocol == "tcp"
    assert rule.port == "22"


def test_nft_parser_marks_unknown_webnas_expression_read_only() -> None:
    payload = '{"nftables":[{"rule":{"family":"inet","table":"webnas","chain":"input","handle":6,"expr":[{"match":{"op":"==","left":{"ct":{"key":"state"}},"right":"established"}},{"accept":null}]}}]}'
    assert parse_nft_rules(payload)[0].editable is False
