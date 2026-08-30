from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import PolicyDocument, PolicyRule


class PolicyExpressionError(ValueError):
    pass


_MISSING = object()
_ALLOWED_OPERATORS = {
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "contains",
    "not_contains",
    "exists",
    "starts_with",
    "ends_with",
}


@dataclass(slots=True)
class _Budget:
    nodes: int = 0


class PolicyEngine:
    """Deterministic evaluator for the WebNAS declarative policy DSL.

    Policy documents never execute Python, shell commands, templates or other
    embedded code. Assertions are reduced to an allowlisted set of operators.
    """

    MAX_DEPTH = 12
    MAX_NODES = 512

    def validate(self, document: PolicyDocument) -> None:
        budget = _Budget()
        for rule in document.spec.rules:
            self._validate_expression(rule.assertion, 0, budget)

    def evaluate(self, document: PolicyDocument, facts: dict[str, Any]) -> dict[str, Any]:
        self.validate(document)
        results = [self._evaluate_rule(rule, facts) for rule in document.spec.rules]
        passed = sum(item["status"] == "pass" for item in results)
        failed = sum(item["status"] == "fail" for item in results)
        errors = sum(item["status"] == "error" for item in results)
        total = len(results)
        score = round((passed / total) * 100) if total else 100
        return {
            "policy_id": document.metadata.name,
            "enabled": document.spec.enabled,
            "compliant": failed == 0 and errors == 0,
            "score": score,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "total": total,
            "results": results,
        }

    def _evaluate_rule(self, rule: PolicyRule, facts: dict[str, Any]) -> dict[str, Any]:
        try:
            matched, evidence = self._evaluate_expression(rule.assertion, facts)
            status = "pass" if matched else "fail"
            error = None
        except (PolicyExpressionError, TypeError, ValueError) as exc:
            status = "error"
            evidence = []
            error = str(exc)
        return {
            "id": rule.id,
            "severity": rule.severity,
            "description": rule.description,
            "message": rule.message,
            "status": status,
            "error": error,
            "evidence": evidence,
        }

    def _validate_expression(self, expression: Any, depth: int, budget: _Budget) -> None:
        if depth > self.MAX_DEPTH:
            raise PolicyExpressionError("assertion nesting exceeds the maximum depth")
        budget.nodes += 1
        if budget.nodes > self.MAX_NODES:
            raise PolicyExpressionError("policy contains too many assertion nodes")
        if not isinstance(expression, dict) or not expression:
            raise PolicyExpressionError("assert must be a non-empty object")

        combinators = [key for key in ("all", "any", "not") if key in expression]
        if combinators:
            if len(combinators) != 1 or len(expression) != 1:
                raise PolicyExpressionError("all, any and not cannot be mixed with other assertion keys")
            key = combinators[0]
            value = expression[key]
            if key == "not":
                self._validate_expression(value, depth + 1, budget)
                return
            if not isinstance(value, list) or not value or len(value) > 64:
                raise PolicyExpressionError(f"{key} must be a non-empty list with at most 64 assertions")
            for item in value:
                self._validate_expression(item, depth + 1, budget)
            return

        allowed = {"path", "operator", "value"}
        if set(expression) - allowed:
            raise PolicyExpressionError("assertion contains unsupported keys")
        path = expression.get("path")
        operator = expression.get("operator")
        if not isinstance(path, str) or not path or len(path) > 256:
            raise PolicyExpressionError("assertion path must be a non-empty string")
        if not isinstance(operator, str) or operator not in _ALLOWED_OPERATORS:
            raise PolicyExpressionError(f"unsupported assertion operator: {operator}")
        if operator != "exists" and "value" not in expression:
            raise PolicyExpressionError(f"operator {operator} requires value")
        if operator == "exists" and "value" in expression and not isinstance(expression["value"], bool):
            raise PolicyExpressionError("exists value must be boolean when supplied")

    def _evaluate_expression(self, expression: dict[str, Any], facts: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
        if "all" in expression:
            evidence: list[dict[str, Any]] = []
            matches: list[bool] = []
            for item in expression["all"]:
                matched, item_evidence = self._evaluate_expression(item, facts)
                matches.append(matched)
                evidence.extend(item_evidence)
            return all(matches), evidence
        if "any" in expression:
            evidence = []
            matches = []
            for item in expression["any"]:
                matched, item_evidence = self._evaluate_expression(item, facts)
                matches.append(matched)
                evidence.extend(item_evidence)
            return any(matches), evidence
        if "not" in expression:
            matched, evidence = self._evaluate_expression(expression["not"], facts)
            return not matched, evidence

        path = expression["path"]
        operator = expression["operator"]
        expected = expression.get("value")
        actual = self._resolve_path(facts, path)
        matched = self._compare(actual, operator, expected)
        evidence = [{
            "path": path,
            "operator": operator,
            "expected": expected,
            "present": actual is not _MISSING,
            "actual": None if actual is _MISSING else actual,
            "matched": matched,
        }]
        return matched, evidence

    @staticmethod
    def _resolve_path(facts: Any, path: str) -> Any:
        current = facts
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
                continue
            if isinstance(current, list) and part.isdigit():
                index = int(part)
                if 0 <= index < len(current):
                    current = current[index]
                    continue
            return _MISSING
        return current

    @staticmethod
    def _compare(actual: Any, operator: str, expected: Any) -> bool:
        if operator == "exists":
            return (actual is not _MISSING) is (True if expected is None else expected)
        if actual is _MISSING:
            return False
        if operator == "eq":
            return actual == expected
        if operator == "ne":
            return actual != expected
        if operator == "gt":
            return actual > expected
        if operator == "gte":
            return actual >= expected
        if operator == "lt":
            return actual < expected
        if operator == "lte":
            return actual <= expected
        if operator == "in":
            if not isinstance(expected, (list, tuple, set, str, dict)):
                raise PolicyExpressionError("in requires a collection value")
            return actual in expected
        if operator == "not_in":
            if not isinstance(expected, (list, tuple, set, str, dict)):
                raise PolicyExpressionError("not_in requires a collection value")
            return actual not in expected
        if operator in {"contains", "not_contains"}:
            if not isinstance(actual, (list, tuple, set, str, dict)):
                raise PolicyExpressionError(f"{operator} requires the actual value to be a collection")
            contained = expected in actual
            return contained if operator == "contains" else not contained
        if operator in {"starts_with", "ends_with"}:
            if not isinstance(actual, str) or not isinstance(expected, str):
                raise PolicyExpressionError(f"{operator} requires string values")
            return actual.startswith(expected) if operator == "starts_with" else actual.endswith(expected)
        raise PolicyExpressionError(f"unsupported assertion operator: {operator}")
