# Webhook Manager

Webhook Manager (`webhook-manager`) is the central outbound webhook delivery service for WebNAS. It subscribes to the existing process event bus instead of introducing a second event system.

## Webhook definitions

Each webhook stores only non-secret configuration:

- name and description;
- enabled state;
- URL;
- method (`POST`, `PUT`, `PATCH`);
- subscribed event names;
- timeout;
- maximum attempts;
- safe custom headers;
- authentication mode;
- Secrets Manager `secret_id` reference;
- optional HMAC `signing_secret_id` reference;
- explicit private-network permission;
- creation/update metadata.

Bearer tokens, passwords, API keys and HMAC keys are never stored in the Webhook Manager database.

## Secrets Manager integration

Webhook authentication and signing values are resolved through `app.modules.secrets_manager.public`. A referenced secret must exist and include `webhook-manager` in its `shared_with` allowlist.

Supported authentication modes:

- none;
- Bearer token;
- Basic Auth (username + secret from one Secrets Manager entry);
- API-key header;
- custom secret header.

Secret material exists only in backend memory while the request headers/signature are constructed. Request authentication headers are never persisted in delivery records.

## Event registry

The built-in registry includes events such as:

- `host.created`
- `host.updated`
- `host.deleted`
- `host.online`
- `host.offline`
- `operation.completed`
- `operation.failed`
- `fail2ban.ip_banned`
- `fail2ban.ip_unbanned`
- `fail2ban.jail_changed`
- `fail2ban.service_changed`
- `secret.created`
- `secret.updated`
- `secret.deleted`
- `backup.completed`

The registry is extensible at runtime through `register_event_type()`. Webhook Manager subscribes to newly registered types without requiring a second event broker.

## Delivery model

The event handler only redacts the event payload and enqueues delivery work in a bounded process-local queue. Network I/O therefore does not block the request that emitted the event.

Each delivery attempt records:

- delivery ID;
- webhook ID;
- event ID/type;
- attempt number;
- `success`, `failed`, or `retry` state;
- HTTP status when available;
- duration;
- error category;
- bounded, redacted response preview;
- timestamp.

Raw event payloads, request headers and secret values are not persisted in delivery history.

Failures retry with exponential backoff up to the configured maximum attempt count. Timeouts are bounded per webhook. The worker queue itself is bounded; queue overflow is recorded as a failed delivery rather than consuming unlimited memory.

## HMAC signing

When `signing_secret_id` is set, the manager sends:

- `X-WebNAS-Event`
- `X-WebNAS-Delivery`
- `X-WebNAS-Timestamp`
- `X-WebNAS-Signature`

The body is deterministic sorted JSON. The signature is HMAC-SHA256 over:

`<timestamp>.<body-bytes>`

The signature header is formatted as `sha256=<hex digest>`.

## SSRF controls

Webhook URLs are centrally validated before save and again immediately before every delivery attempt.

The validator:

- allows only `http` and `https`;
- requires a hostname;
- rejects credentials embedded in the URL;
- rejects fragments and invalid ports;
- rejects localhost;
- resolves hostnames and checks all returned addresses;
- always rejects loopback, link-local, multicast, unspecified and reserved ranges;
- rejects private addresses by default;
- allows private RFC1918/ULA infrastructure only when an administrator explicitly enables the webhook's `allow_private_networks` option.

Re-resolving before every attempt ensures a hostname that changes to a blocked range is rejected on the next send/retry. Private-network support remains available because WebNAS is an infrastructure administration product.

## Custom headers

Custom headers cannot override security-sensitive transport headers managed by Webhook Manager. `Authorization`, `Cookie`, `Host`, `Content-Length`, `Transfer-Encoding` and `X-WebNAS-Signature` are rejected in custom header configuration. CR/LF/NUL characters are rejected.

## Test delivery

`POST /webhooks/{id}/test` sends a real bounded test event and returns the delivery metadata: status, HTTP status, duration, error category and redacted response preview. Credentials and authentication headers are excluded.

## API

Base path: `/api/modules/webhook-manager`.

Endpoints:

- `GET /dashboard`
- `GET /events`
- `GET /webhooks`
- `GET /webhooks/{id}`
- `POST /webhooks`
- `PUT /webhooks/{id}`
- `DELETE /webhooks/{id}`
- `PUT /webhooks/{id}/enabled`
- `POST /webhooks/{id}/test`
- `GET /deliveries`

## RBAC

Permissions:

- `webhook-manager.view`
- `webhook-manager.manage`
- `webhook-manager.test`
- `webhook-manager.deliveries.view`
- `webhook-manager.configure`

Administrators receive all permissions. Operators may manage/test webhooks and inspect deliveries. Auditors receive read-only webhook/delivery access.

## Operational limitation

The delivery queue is process-local rather than a durable external queue. Delivery records are durable SQLite rows, but work that is only queued in memory when the WebNAS process terminates cannot be resumed automatically. This keeps the implementation aligned with the current WebNAS in-process event architecture; a future durable jobs backend can replace the queue behind the same webhook API.
