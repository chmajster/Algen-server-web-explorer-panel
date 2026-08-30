# Policy-as-Code Engine

Policy-as-Code Engine stores WebNAS policies as real YAML or JSON files and evaluates them with a declarative, non-executable DSL.

## Storage

The default policy directory is `/var/lib/webnas/policies`. Set `WEBNAS_POLICY_DIR` to use another directory, for example in tests or a custom deployment. Files are written atomically with mode `0600`. Policy IDs are derived from `metadata.name` and become `<id>.yaml` or `<id>.json`.

## Document format

```yaml
apiVersion: webnas/v1
kind: PolicySet
metadata:
  name: linux-baseline
  description: Baseline policy
  labels:
    scope: linux
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
```

Every policy contains one or more rules. Rule IDs must be unique inside a policy. The engine validates the complete expression tree before evaluation.

## Assertion DSL

Leaf assertions use `path`, `operator` and, except for `exists`, `value`.

Supported operators:

- `eq`, `ne`
- `gt`, `gte`, `lt`, `lte`
- `in`, `not_in`
- `contains`, `not_contains`
- `exists`
- `starts_with`, `ends_with`

Assertions can be combined with `all`, `any` and `not`:

```yaml
assert:
  all:
    - path: firewall.enabled
      operator: eq
      value: true
    - path: firewall.default_policy
      operator: in
      value: [drop, reject]
```

Paths use dot notation and can address numeric list indexes, for example `interfaces.0.name`.

## Security model

Policy source is data, never executable code. The evaluator does not use `eval`, `exec`, shell commands, templates, dynamic imports or arbitrary regular expressions. Expression depth and node counts are bounded. YAML is parsed with `safe_load` and policy source size is limited to 256 KiB.

RBAC permissions:

- `policy.view` — list and read policies and summary information.
- `policy.evaluate` — validate policy source and evaluate policies against supplied JSON facts.
- `policy.manage` — create, update and delete policy files.

Admins receive all three permissions. Operators receive view and evaluate. Auditors receive view only.

## API

- `GET /api/modules/policy-as-code/summary`
- `GET /api/modules/policy-as-code/policies`
- `GET /api/modules/policy-as-code/policies/{id}`
- `POST /api/modules/policy-as-code/policies`
- `PUT /api/modules/policy-as-code/policies/{id}`
- `DELETE /api/modules/policy-as-code/policies/{id}`
- `POST /api/modules/policy-as-code/validate`
- `POST /api/modules/policy-as-code/evaluate`

`POST /evaluate` supports three modes: evaluate a stored policy by `policy_id`, evaluate ad-hoc `source` with its `format`, or omit both to evaluate all enabled stored policies.

## Example evaluation input

```json
{
  "facts": {
    "ssh": {
      "permit_root_login": "no"
    },
    "firewall": {
      "enabled": true,
      "default_policy": "drop"
    }
  }
}
```

The response contains the aggregate score and per-rule evidence showing the resolved path, expected value, actual value and match result.
