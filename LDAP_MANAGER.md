# LDAP Manager

LDAP Manager is an optional WebNAS module for administering remote LDAP directories. It is not an authentication provider and it is not required for WebNAS LDAP login.

## Architectural boundary

Two independent domains exist:

```text
Settings -> Authentication -> LDAP Authentication
  WebNAS user -> LDAP bind/search -> WebNAS identity -> WebNAS RBAC -> session

Modules -> LDAP Manager
  WebNAS administrator -> LDAP Manager -> remote LDAP / Active Directory / FreeIPA
```

LDAP Authentication owns `ldap-auth.sqlite3` and the Secrets Manager credential `auth-ldap-bind-password`. LDAP Manager owns `ldap-manager.sqlite3` and one secret per connection named `ldap-manager-connection-<id>-bind-password`. Neither subsystem reads or copies the other's credentials. Removing or disabling LDAP Manager does not disable LDAP Authentication.

## Connections

LDAP Manager supports multiple independent connections. Each connection has a name, directory type, ordered servers, LDAP/StartTLS/LDAPS mode, TLS verification, optional custom CA, Base DN, Bind DN, its own Bind Password, and connection/operation timeouts.

Directory types are Generic LDAP, LDAP/OpenLDAP, Active Directory and FreeIPA. Provider-specific adapters expose only capabilities supported by the selected directory.

TLS certificate verification is enabled by default. Disabling it affects only that connection. WebNAS never disables TLS verification globally.

## Features

The module exposes:

- Overview/dashboard with connection state, latency, directory counts and provider capabilities where available;
- Directory Browser with Base DN, scope, LDAP filter, selected attributes and paged results;
- user CRUD, enable/disable/unlock when supported, password reset, rename/move and group membership;
- group CRUD and membership handling for `member`, `uniqueMember` and `memberUid` models;
- OU/container create, update, move and delete;
- read-only schema discovery for objectClasses and attributeTypes;
- diagnostics for DNS/TCP/TLS/bind/rootDSE/search and directory metadata;
- CSV export/import and LDIF export/import;
- bulk operations with dry-run/preview before execution.

The Active Directory adapter understands attributes such as `sAMAccountName`, `userPrincipalName`, `objectGUID`, `objectSid`, `memberOf`, `userAccountControl`, `pwdLastSet`, `lockoutTime` and `accountExpires`. OpenLDAP support covers common `uid`, `cn`, `sn`, `mail`, `uidNumber`, `gidNumber`, `homeDirectory`, `loginShell`, `member`, `memberUid`, `uniqueMember` and `entryUUID` layouts without assuming every attribute exists. FreeIPA uses LDAP-compatible directory operations and capability detection rather than attempting to implement the entire FreeIPA HTTP API.

## API

The module is rooted at:

```text
/api/modules/ldap-manager
```

Key resources include `/connections`, `/connections/{id}/overview`, `/directory`, `/users`, `/groups`, `/ous`, `/schema`, `/search`, `/diagnostics`, `/import`, `/export` and `/bulk`.

Every endpoint enforces backend RBAC. UI visibility is not treated as an authorization boundary.

## RBAC

Permissions:

```text
ldap.connections.read
ldap.connections.manage
ldap.directory.read
ldap.users.read
ldap.users.create
ldap.users.update
ldap.users.delete
ldap.users.password_reset
ldap.groups.read
ldap.groups.create
ldap.groups.update
ldap.groups.delete
ldap.ou.read
ldap.ou.manage
ldap.schema.read
ldap.import
ldap.export
ldap.bulk.execute
ldap.diagnostics.read
```

These permissions are registered in the existing WebNAS Identity/RBAC system; LDAP Manager does not implement a parallel role system.

## Audit and secrets

Administrative operations are written to the existing Activity/Audit subsystem with actor, connection, action, target, result and timestamp context. Passwords, Bind Passwords and raw credentials are never included in audit details.

Bind Passwords are stored only through Secrets Manager. Public connection responses expose `bind_password_configured: true|false`, never the password or secret identifier.

## Security

- user-controlled LDAP filter values are RFC4515 escaped;
- DN values are parsed/validated and RDN values are escaped before construction;
- generic attribute modification blocks password, immutable-ID and account-control attributes that require dedicated operations;
- LDAP targets reject link-local, multicast, unspecified and cloud metadata addresses while permitting private directory networks;
- StartTLS and LDAPS failures are surfaced as connection/TLS errors rather than ignored;
- destructive operations require dedicated mutating endpoints and CSRF-protected WebNAS sessions;
- provider-specific operations avoid treating Active Directory as generic OpenLDAP when semantics differ.

## Authentication is separate

For WebNAS login configuration, failover, access policy and LDAP-group-to-WebNAS-RBAC mapping, use [LDAP_AUTHENTICATION.md](LDAP_AUTHENTICATION.md). Do not create an LDAP Manager connection to configure WebNAS login.