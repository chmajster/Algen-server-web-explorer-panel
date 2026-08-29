# Alert Manager

Alert Manager turns existing WebNAS operational state into a durable alert lifecycle. It does not create a second monitoring inventory: sources emit or collect conditions from durable jobs, Module Registry health, Hosts Manager state and existing resource/operation hooks.

## Lifecycle

Every event is matched to enabled rules with the same `source`. A stable SHA-256 fingerprint is calculated from rule id, source and event key. Repeated observations update one alert and increment `occurrences` instead of creating duplicates.

States are:

- `firing` — the condition is active;
- `acknowledged` — an operator is handling the condition; repeated observations remain deduplicated and do not resend notifications;
- `resolved` — the condition cleared or was explicitly resolved.

A resolved fingerprint can fire again. The same alert record returns to `firing`, acknowledgement metadata is cleared and a new notification is queued.

Rules define severity, a per-rule cooldown, optional exact-match fields and notification sink assignments. A cooldown suppresses repeated firing notifications without hiding occurrence counts.

## Sources

The first release wires these sources directly:

- `job.failed` — emitted after a durable `JobService` job is committed as failed; a later successful job with the same module/type resolves the condition;
- `module.health` — collected from the existing `ModuleRegistry.health()` result once per minute;
- `host.offline` — collected from the existing batch-enriched Hosts Manager registry once per minute.

Built-in rule namespaces also reserve `job.interrupted`, `operation.failed`, `resource.threshold` and `auth.required`. Existing producers can emit those conditions through `AlertService.fire()` without introducing parallel metric storage.

Collectors and notification workers start only on the active blue/green slot. A candidate release does not send alerts before promotion.

## Notification sinks

Supported sinks are:

- generic HTTPS JSON webhook;
- ntfy-compatible HTTPS webhook;
- SMTP with optional STARTTLS and authentication.

Webhook HTTP URLs are rejected. Sink configuration including URL tokens and SMTP credentials is encrypted at rest with a dedicated WAC2 key at `<data_dir>/secrets/alerts.key`. The API only returns sink metadata such as id, name, type, enabled and `configured=true`; it never returns the URL, token, password or encrypted envelope.

All outgoing payloads pass through the shared core redaction layer. Test-delivery diagnostics are also redacted before delivery, Activity Center audit and API response.

## Durable delivery and retry

Each notification is a durable row in the Alert Manager SQLite database. Delivery attempts are bounded to five. Failures retry with exponential delay beginning at 30 seconds and capped at 15 minutes. After the fifth failed attempt the delivery becomes terminal `failed`. Stored `last_error` contains only bounded, redacted diagnostic text and never sink credentials.

## RBAC and audit

The first release maps Alert Manager operations onto existing WebNAS permission boundaries:

- `system.status` — view dashboard, alerts and rules;
- `modules.configure` — acknowledge or resolve alerts;
- `settings.edit_system` — create/update/delete rules and notification sinks and trigger a test delivery.

Mutating routes use the normal permission dependency and therefore require a valid CSRF token. Rule/sink changes and operator state transitions are written to Activity Center without sink secrets.

## API

The API is under `/api/alerts`:

- `GET /api/alerts/dashboard`
- `GET /api/alerts`
- `POST /api/alerts/{id}/acknowledge`
- `POST /api/alerts/{id}/resolve`
- `GET|POST /api/alerts/rules`
- `PUT|DELETE /api/alerts/rules/{id}`
- `GET|POST /api/alerts/sinks`
- `PUT|DELETE /api/alerts/sinks/{id}`
- `POST /api/alerts/sinks/{id}/test`

The native `Alert Manager` desktop application presents alert status, acknowledgements, rules and sink configuration. Existing sink secrets are intentionally write-only; editing a secret requires entering it again.
