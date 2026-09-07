# WebNAS RBAC

> Current implementation should be treated as development / non-production code until a dedicated security review, penetration testing, configuration hardening and production validation are completed.

## Architecture

WebNAS uses one authorization graph stored in the existing `identity.sqlite3`. The dynamic RBAC tables extend the existing identity subsystem; they are not a separate authorization database. Authentication remains provider-specific (`local`, `pam`, `ldap`) and authorization resolves the authenticated `SessionUser` through `PermissionService`.

Core concepts:

- **User** — an authenticated identity identified by provider plus immutable identity ID. Username is display/routing metadata and is not the sole identity key.
- **Group** — local WebNAS group. A user may belong to many groups.
- **ExternalGroup** — LDAP/Active Directory group keyed by provider plus immutable external ID and DN.
- **Role** — named reusable collection of permission grants/denies. Roles are data, not frontend constants.
- **Permission** — canonical backend capability such as `files.read`, `docker.manage_containers` or `access.manage_roles`.
- **Policy** — conditional grant/deny for a subject and optional resource scope.
- **Resource** — `{resource_type, resource_id, scope}` passed to authorization.
- **Assignment** — direct user-role, group-role or external-group-role edge.
- **IdentityProvider** — authentication source; current session providers are `local`, `pam` and `ldap`.

The resolver computes:

`direct roles + local group roles + LDAP group roles + policy grants - explicit denies`

Deny always overrides allow. If no matching allow exists, the result is DENY.

## System roles

The schema seeds protected roles:

- Administrator
- Operator
- Auditor
- User
- Read Only

System roles cannot be deleted accidentally. Administrators can duplicate a system role and then edit the custom copy. Existing explicit legacy assignments are migrated on first RBAC authorization. The legacy implicit/default `user` role is deliberately not migrated; identities without an explicit grant use default-deny.

## Permissions

The canonical permission registry remains `app.identity.permissions`. `PermissionService` consumes that registry and also accepts compatibility aliases such as `rbac.manage`, `ldap.manage`, `docker.manage`, `services.read` and `files.write`. Aliases are normalized to canonical backend permissions before storage/evaluation.

Adding a new permission:

1. Add it to `Permission` in `backend/app/identity/permissions.py`.
2. Add metadata/category handling where required.
3. Add it to the appropriate system role(s) only when the role should grant it.
4. Protect the backend endpoint with centralized authorization.
5. Add resolver/API tests. Hiding a frontend control is never authorization.

## Resolution and explain mode

`PermissionService` is the central resolver. Relevant methods:

```python
permission_service().can(user, "docker.manage", Resource("container", "nginx", "*"))
permission_service().authorize(user, "files.write", Resource("files", "home", "/home/jan"))
permission_service().explain(user, "docker.manage", resource)
```

Explain mode returns ALLOW/DENY, the normalized permission, resource and every source edge used for the decision. Source types include `direct-role`, `local-group`, `ldap-group` and `policy`.

## Resource scopes

Role permissions and policies may constrain:

- `resource_type`
- `resource_id`
- `scope`

Examples:

- `files.read` on `files:public` scope `/data/public`
- `files.write` on `files:home` scope `/home/jan`
- `docker.manage_containers` on `container:nginx`
- `services.restart` on `service:nginx`

A scope matches the exact scope or a descendant path. A global `*` scope matches all scopes for the resource.

## Policies

Policies contain an effect (`allow` or `deny`), permission, optional resource tuple, subjects and conditions. Current subject types are user, local group, external group and provider. The first condition implemented by the core engine is `auth_provider`. The schema intentionally stores conditions as structured JSON so MFA, trusted network/IP, device posture, authentication method and time windows can be added without encoding those rules in frontend code.

A deny policy has precedence over all matching role grants.

## Local groups

Local RBAC groups are application-owned. They contain members and role edges. Membership is keyed by authentication provider and immutable identity ID, preventing a PAM user and LDAP user with the same username from becoming one security principal.

Groups with `source=ldap` are managed. Their membership cannot be modified by local group-edit endpoints.

## LDAP / Active Directory

LDAP authentication configuration remains in the existing LDAP Authentication subsystem, which already provides:

- multiple servers/failover,
- LDAP, StartTLS and LDAPS,
- certificate verification and optional CA certificate,
- Base DN/user/group search bases,
- bind DN with bind password stored through Secrets Manager,
- user/group filters and configurable attributes,
- `uid`, `cn`, `mail`, `member`, `memberOf`, `sAMAccountName`, `userPrincipalName`, DN/immutable-ID compatible mapping,
- escaped LDAP filter values,
- connect/operation timeouts,
- bounded searches and diagnostics.

The RBAC layer stores external groups by immutable external ID and DN and maps them many-to-many to roles. An external group may map to many roles and one role may be linked from many external groups.

Never infer permissions from an LDAP group name. A wizard may create a role named after a selected group, but the administrator must explicitly select permissions.

## Nested groups

Nested membership must be materialized during LDAP synchronization as effective external memberships. Synchronizers must apply a visited-set, configurable maximum depth and maximum expanded-node count. Cycles are treated as directory-data errors, not as recursive grants. Direct memberships are retained separately from inherited memberships so explain mode can identify the effective source.

## LDAP synchronization and failure semantics

Supported lifecycle semantics are manual synchronization, refresh at login and periodic synchronization. LDAP records use `active`, `disabled` and `missing_from_source`. A temporary LDAP failure must not delete cached users or group memberships. Local/PAM emergency administration remains independent from LDAP availability.

Directory health is represented as Online, Degraded or Offline based on diagnostics/synchronization state. Bind credentials and raw secrets must never be written to diagnostics or audit logs.

## Security requirements for LDAP

- Prefer StartTLS or LDAPS with certificate verification enabled.
- Reject unsafe LDAP targets and metadata/link-local targets.
- Escape all user-controlled LDAP filter values.
- Bound connection and operation timeouts.
- Bound result size and page searches.
- Never log bind passwords, recovered secrets or full exception payloads containing credentials.
- Never use UI visibility as an access-control decision.

## Cache

Effective permission sources may be cached for a short period. Mutations of roles, direct assignments, local groups, LDAP memberships/mappings or policies must call `PermissionService.invalidate()` before returning success. Revocation tests cover this behavior. Authentication sessions remain independently revocable.

## Audit

RBAC writes are recorded in `rbac_audit` with:

- actor
- action
- target
- before JSON
- after JSON
- timestamp
- source IP

The same actions should also continue to flow into the application activity log where cross-module operational visibility is required.

## API

Primary endpoints:

- `GET /api/rbac/permissions`
- `GET|POST /api/rbac/roles`
- `GET|PUT|DELETE /api/rbac/roles/{id}`
- `POST /api/rbac/roles/{id}/duplicate`
- `GET|POST /api/rbac/groups`
- `PUT /api/rbac/groups/{id}/members`
- `POST /api/rbac/users/{username}/roles`
- `DELETE /api/rbac/users/{username}/roles/{role_id}`
- `GET /api/rbac/users/{username}/effective-permissions`
- `GET|POST /api/rbac/policies`
- `POST /api/rbac/simulate`
- `GET /api/rbac/external-groups`
- `POST /api/rbac/external-group-mappings`
- `GET /api/rbac/audit`

Existing LDAP configuration/testing endpoints remain under `/api/settings/authentication/ldap` during compatibility migration. New clients should treat the dynamic RBAC endpoints as the authorization source of truth.

## Admin UI model

The Access and Security area should expose Users, Groups, Roles, Permissions, Policies, LDAP / Active Directory, Group Mapping, Effective Permissions and Audit Log. The role editor groups permissions by category, allows selecting/unselecting a whole category, supports search, and shows each effective grant with its source chain.

## Non-production status

Passing unit/integration tests is not evidence of production readiness. Before production use, perform a dedicated security architecture review, penetration test, LDAP/AD interoperability validation, migration rehearsal, least-privilege review, secret-storage review, TLS hardening and operational recovery testing.