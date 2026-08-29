from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ..config import get_config
from ..core.redaction import redact, redact_text
from ..modules.ansible_controller.public_security import CredentialCipher
from ..sqlite_utils import ClosingConnection
from .delivery import DeliveryError, deliver
from .models import AlertEvent, AlertSeverity, AlertState, RuleInput, SinkInput


DEFAULT_RULES = (
    ("durable-job-failure", "Failed durable job", "job.failed", AlertSeverity.error, 300),
    ("interrupted-job", "Interrupted durable job", "job.interrupted", AlertSeverity.warning, 300),
    ("module-health", "Module health degraded", "module.health", AlertSeverity.error, 300),
    ("host-offline", "Host or agent offline", "host.offline", AlertSeverity.warning, 900),
    ("operation-failure", "Operational failure", "operation.failed", AlertSeverity.error, 300),
    ("resource-threshold", "Resource threshold", "resource.threshold", AlertSeverity.warning, 600),
    ("authentication-required", "Authentication required", "auth.required", AlertSeverity.warning, 900),
)
MAX_DELIVERY_ATTEMPTS = 5


def _id() -> str:
    return secrets.token_hex(16)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


class AlertService:
    def __init__(self, path: Path | None = None, key_path: Path | None = None) -> None:
        root = Path(get_config().paths.data_dir)
        self.path = path or root / "alerts" / "alerts.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        self.cipher = CredentialCipher(key_path or root / "secrets" / "alerts.key")
        self._lock = threading.RLock()
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS alert_rules(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    cooldown_seconds INTEGER NOT NULL,
                    enabled INTEGER NOT NULL,
                    matcher_json TEXT NOT NULL DEFAULT '{}',
                    sink_ids_json TEXT NOT NULL DEFAULT '[]',
                    built_in INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    updated_by TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_alert_rules_source ON alert_rules(source,enabled);

                CREATE TABLE IF NOT EXISTS alert_sinks(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    type TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    encrypted_config TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    updated_by TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alerts(
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    rule_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    object_ref TEXT NOT NULL DEFAULT '',
                    severity TEXT NOT NULL,
                    state TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    occurrences INTEGER NOT NULL DEFAULT 1,
                    first_seen_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL,
                    last_notified_at REAL,
                    acknowledged_at REAL,
                    acknowledged_by TEXT NOT NULL DEFAULT '',
                    acknowledgement_note TEXT NOT NULL DEFAULT '',
                    resolved_at REAL,
                    resolved_by TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(rule_id) REFERENCES alert_rules(id) ON DELETE RESTRICT
                );
                CREATE INDEX IF NOT EXISTS idx_alerts_state_seen ON alerts(state,last_seen_at DESC);
                CREATE INDEX IF NOT EXISTS idx_alerts_source_key ON alerts(source,event_key);

                CREATE TABLE IF NOT EXISTS alert_deliveries(
                    id TEXT PRIMARY KEY,
                    alert_id TEXT NOT NULL,
                    sink_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 5,
                    next_attempt_at REAL NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(alert_id) REFERENCES alerts(id) ON DELETE CASCADE,
                    FOREIGN KEY(sink_id) REFERENCES alert_sinks(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_alert_delivery_due ON alert_deliveries(state,next_attempt_at);
                """
            )
            now = time.time()
            for rule_id, name, source, severity, cooldown in DEFAULT_RULES:
                connection.execute(
                    """
                    INSERT INTO alert_rules(
                        id,name,source,severity,cooldown_seconds,enabled,matcher_json,
                        sink_ids_json,built_in,created_at,updated_at,updated_by
                    ) VALUES (?,?,?,?,?,1,'{}','[]',1,?,?,?)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (rule_id, name, source, severity.value, cooldown, now, now, "system"),
                )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def fingerprint(rule_id: str, source: str, key: str) -> str:
        raw = f"{rule_id}\0{source}\0{key}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _rule(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "source": str(row["source"]),
            "severity": str(row["severity"]),
            "cooldown_seconds": int(row["cooldown_seconds"]),
            "enabled": bool(row["enabled"]),
            "matcher": _loads(str(row["matcher_json"]), {}),
            "sink_ids": _loads(str(row["sink_ids_json"]), []),
            "built_in": bool(row["built_in"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "updated_by": str(row["updated_by"]),
        }

    @staticmethod
    def _sink_public(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "type": str(row["type"]),
            "enabled": bool(row["enabled"]),
            "configured": bool(row["encrypted_config"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "updated_by": str(row["updated_by"]),
        }

    @staticmethod
    def _alert(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "fingerprint": str(row["fingerprint"]),
            "rule_id": str(row["rule_id"]),
            "source": str(row["source"]),
            "event_key": str(row["event_key"]),
            "title": str(row["title"]),
            "object_ref": str(row["object_ref"]),
            "severity": str(row["severity"]),
            "state": str(row["state"]),
            "details": _loads(str(row["details_json"]), {}),
            "occurrences": int(row["occurrences"]),
            "first_seen_at": float(row["first_seen_at"]),
            "last_seen_at": float(row["last_seen_at"]),
            "last_notified_at": float(row["last_notified_at"]) if row["last_notified_at"] is not None else None,
            "acknowledged_at": float(row["acknowledged_at"]) if row["acknowledged_at"] is not None else None,
            "acknowledged_by": str(row["acknowledged_by"]),
            "acknowledgement_note": str(row["acknowledgement_note"]),
            "resolved_at": float(row["resolved_at"]) if row["resolved_at"] is not None else None,
            "resolved_by": str(row["resolved_by"]),
        }

    def list_rules(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM alert_rules ORDER BY built_in DESC,name COLLATE NOCASE").fetchall()
        return [self._rule(row) for row in rows]

    def save_rule(self, payload: RuleInput, actor: str, rule_id: str | None = None) -> dict[str, Any]:
        now = time.time()
        identifier = rule_id or _id()
        sink_ids = list(dict.fromkeys(payload.sink_ids))
        with self._lock, self.connect() as connection:
            if sink_ids:
                placeholders = ",".join("?" for _ in sink_ids)
                count = connection.execute(
                    f"SELECT COUNT(*) FROM alert_sinks WHERE id IN ({placeholders})",  # noqa: S608
                    sink_ids,
                ).fetchone()[0]
                if int(count) != len(sink_ids):
                    raise KeyError("notification sink not found")
            existing = connection.execute("SELECT created_at,built_in FROM alert_rules WHERE id=?", (identifier,)).fetchone()
            created_at = float(existing["created_at"]) if existing else now
            built_in = int(existing["built_in"]) if existing else 0
            connection.execute(
                """
                INSERT INTO alert_rules(id,name,source,severity,cooldown_seconds,enabled,matcher_json,sink_ids_json,built_in,created_at,updated_at,updated_by)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,source=excluded.source,severity=excluded.severity,
                    cooldown_seconds=excluded.cooldown_seconds,enabled=excluded.enabled,
                    matcher_json=excluded.matcher_json,sink_ids_json=excluded.sink_ids_json,
                    updated_at=excluded.updated_at,updated_by=excluded.updated_by
                """,
                (
                    identifier,
                    payload.name,
                    payload.source,
                    payload.severity.value,
                    payload.cooldown_seconds,
                    int(payload.enabled),
                    _json(redact(payload.matcher)),
                    _json(sink_ids),
                    built_in,
                    created_at,
                    now,
                    actor,
                ),
            )
            row = connection.execute("SELECT * FROM alert_rules WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise RuntimeError("alert rule write failed")
        return self._rule(row)

    def delete_rule(self, rule_id: str) -> bool:
        with self._lock, self.connect() as connection:
            row = connection.execute("SELECT built_in FROM alert_rules WHERE id=?", (rule_id,)).fetchone()
            if row is None:
                return False
            if bool(row["built_in"]):
                raise PermissionError("built-in alert rules cannot be deleted")
            used = connection.execute("SELECT 1 FROM alerts WHERE rule_id=? LIMIT 1", (rule_id,)).fetchone()
            if used:
                raise ValueError("alert rule has historical alerts")
            connection.execute("DELETE FROM alert_rules WHERE id=?", (rule_id,))
            return True

    def list_sinks(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM alert_sinks ORDER BY name COLLATE NOCASE").fetchall()
        return [self._sink_public(row) for row in rows]

    @staticmethod
    def _sink_config(payload: SinkInput) -> dict[str, Any]:
        return {
            "type": payload.type.value,
            "url": str(payload.url) if payload.url is not None else "",
            "token": payload.token,
            "smtp_host": payload.smtp_host,
            "smtp_port": payload.smtp_port,
            "smtp_username": payload.smtp_username,
            "smtp_password": payload.smtp_password,
            "smtp_from": payload.smtp_from,
            "smtp_to": payload.smtp_to,
            "smtp_starttls": payload.smtp_starttls,
        }

    def save_sink(self, payload: SinkInput, actor: str, sink_id: str | None = None) -> dict[str, Any]:
        identifier = sink_id or _id()
        now = time.time()
        encrypted = self.cipher.encrypt(
            _json(self._sink_config(payload)),
            associated_data=f"alert-sink:{identifier}",
        )
        with self._lock, self.connect() as connection:
            existing = connection.execute("SELECT created_at FROM alert_sinks WHERE id=?", (identifier,)).fetchone()
            created_at = float(existing["created_at"]) if existing else now
            connection.execute(
                """
                INSERT INTO alert_sinks(id,name,type,enabled,encrypted_config,created_at,updated_at,updated_by)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,type=excluded.type,enabled=excluded.enabled,
                    encrypted_config=excluded.encrypted_config,updated_at=excluded.updated_at,updated_by=excluded.updated_by
                """,
                (identifier, payload.name, payload.type.value, int(payload.enabled), encrypted, created_at, now, actor),
            )
            row = connection.execute("SELECT * FROM alert_sinks WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise RuntimeError("notification sink write failed")
        return self._sink_public(row)

    def delete_sink(self, sink_id: str) -> bool:
        with self._lock, self.connect() as connection:
            row = connection.execute("SELECT 1 FROM alert_sinks WHERE id=?", (sink_id,)).fetchone()
            if row is None:
                return False
            rules = connection.execute("SELECT id,sink_ids_json FROM alert_rules").fetchall()
            for rule in rules:
                if sink_id in _loads(str(rule["sink_ids_json"]), []):
                    raise ValueError("notification sink is assigned to an alert rule")
            connection.execute("DELETE FROM alert_sinks WHERE id=?", (sink_id,))
            return True

    def _decrypt_sink(self, row: sqlite3.Row) -> dict[str, Any]:
        raw = self.cipher.decrypt(
            str(row["encrypted_config"]),
            associated_data=f"alert-sink:{row['id']}",
        )
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("invalid notification sink configuration")
        return {"id": str(row["id"]), "name": str(row["name"]), "type": str(row["type"]), **value}

    @staticmethod
    def _matches(rule: dict[str, Any], event: AlertEvent) -> bool:
        matcher = rule.get("matcher") or {}
        if not isinstance(matcher, dict):
            return False
        safe_details = redact(event.details)
        for key, expected in matcher.items():
            actual: Any
            if key == "object_ref":
                actual = event.object_ref
            else:
                actual = safe_details.get(key) if isinstance(safe_details, dict) else None
            if actual != expected:
                return False
        return True

    def _queue_deliveries(self, connection: sqlite3.Connection, alert_id: str, sink_ids: list[str], now: float) -> int:
        queued = 0
        for sink_id in list(dict.fromkeys(sink_ids))[:32]:
            enabled = connection.execute("SELECT enabled FROM alert_sinks WHERE id=?", (sink_id,)).fetchone()
            if not enabled or not bool(enabled["enabled"]):
                continue
            connection.execute(
                "INSERT INTO alert_deliveries(id,alert_id,sink_id,state,attempt_count,max_attempts,next_attempt_at,last_error,created_at,updated_at) VALUES (?,?,?,'pending',0,?,?, '',?,?)",
                (_id(), alert_id, sink_id, MAX_DELIVERY_ATTEMPTS, now, now, now),
            )
            queued += 1
        return queued

    def fire(self, event: AlertEvent) -> list[dict[str, Any]]:
        now = time.time()
        safe_details = redact(event.details)
        with self._lock, self.connect() as connection:
            rule_rows = connection.execute(
                "SELECT * FROM alert_rules WHERE enabled=1 AND source=? ORDER BY built_in DESC,id",
                (event.source,),
            ).fetchall()
            results: list[dict[str, Any]] = []
            for rule_row in rule_rows:
                rule = self._rule(rule_row)
                if not self._matches(rule, event):
                    continue
                fingerprint = self.fingerprint(rule["id"], event.source, event.key)
                current = connection.execute("SELECT * FROM alerts WHERE fingerprint=?", (fingerprint,)).fetchone()
                severity = (event.severity or AlertSeverity(rule["severity"])).value
                should_notify = False
                if current is None:
                    alert_id = _id()
                    connection.execute(
                        """
                        INSERT INTO alerts(
                            id,fingerprint,rule_id,source,event_key,title,object_ref,severity,state,details_json,
                            occurrences,first_seen_at,last_seen_at,last_notified_at,acknowledged_at,
                            acknowledged_by,acknowledgement_note,resolved_at,resolved_by
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?,NULL,NULL,'','',NULL,'')
                        """,
                        (
                            alert_id,
                            fingerprint,
                            rule["id"],
                            event.source,
                            event.key,
                            redact_text(event.title, limit=256),
                            redact_text(event.object_ref, limit=512),
                            severity,
                            AlertState.firing.value,
                            _json(safe_details),
                            now,
                            now,
                        ),
                    )
                    should_notify = True
                else:
                    alert_id = str(current["id"])
                    previous_state = AlertState(str(current["state"]))
                    last_notified = float(current["last_notified_at"]) if current["last_notified_at"] is not None else None
                    re_firing = previous_state == AlertState.resolved
                    if previous_state != AlertState.acknowledged:
                        should_notify = re_firing or last_notified is None or now - last_notified >= int(rule["cooldown_seconds"])
                    connection.execute(
                        """
                        UPDATE alerts SET title=?,object_ref=?,severity=?,state=?,details_json=?,occurrences=occurrences+1,
                            last_seen_at=?,acknowledged_at=CASE WHEN ? THEN NULL ELSE acknowledged_at END,
                            acknowledged_by=CASE WHEN ? THEN '' ELSE acknowledged_by END,
                            acknowledgement_note=CASE WHEN ? THEN '' ELSE acknowledgement_note END,
                            resolved_at=NULL,resolved_by=''
                        WHERE id=?
                        """,
                        (
                            redact_text(event.title, limit=256),
                            redact_text(event.object_ref, limit=512),
                            severity,
                            AlertState.firing.value if re_firing else previous_state.value,
                            _json(safe_details),
                            now,
                            int(re_firing),
                            int(re_firing),
                            int(re_firing),
                            alert_id,
                        ),
                    )
                queued = 0
                if should_notify:
                    queued = self._queue_deliveries(connection, alert_id, list(rule["sink_ids"]), now)
                    if queued:
                        connection.execute("UPDATE alerts SET last_notified_at=? WHERE id=?", (now, alert_id))
                row = connection.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
                if row is not None:
                    item = self._alert(row)
                    item["queued_deliveries"] = queued
                    results.append(item)
        return results

    def resolve(self, source: str, key: str, actor: str = "system") -> list[dict[str, Any]]:
        now = time.time()
        with self._lock, self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM alerts WHERE source=? AND event_key=? AND state<>?",
                (source, key, AlertState.resolved.value),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                connection.execute(
                    "UPDATE alerts SET state=?,resolved_at=?,resolved_by=?,last_seen_at=? WHERE id=?",
                    (AlertState.resolved.value, now, actor, now, row["id"]),
                )
                rule = connection.execute("SELECT sink_ids_json FROM alert_rules WHERE id=?", (row["rule_id"],)).fetchone()
                if rule:
                    self._queue_deliveries(connection, str(row["id"]), _loads(str(rule["sink_ids_json"]), []), now)
                    connection.execute("UPDATE alerts SET last_notified_at=? WHERE id=?", (now, row["id"]))
                updated = connection.execute("SELECT * FROM alerts WHERE id=?", (row["id"],)).fetchone()
                if updated:
                    result.append(self._alert(updated))
            return result

    def acknowledge(self, alert_id: str, actor: str, note: str = "") -> dict[str, Any] | None:
        now = time.time()
        with self._lock, self.connect() as connection:
            current = connection.execute("SELECT state FROM alerts WHERE id=?", (alert_id,)).fetchone()
            if current is None:
                return None
            if str(current["state"]) == AlertState.resolved.value:
                raise ValueError("resolved alerts cannot be acknowledged")
            connection.execute(
                "UPDATE alerts SET state=?,acknowledged_at=?,acknowledged_by=?,acknowledgement_note=? WHERE id=?",
                (AlertState.acknowledged.value, now, actor, redact_text(note, limit=1000), alert_id),
            )
            row = connection.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
        return self._alert(row) if row else None

    def resolve_alert(self, alert_id: str, actor: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT source,event_key FROM alerts WHERE id=?", (alert_id,)).fetchone()
        if row is None:
            return None
        resolved = self.resolve(str(row["source"]), str(row["event_key"]), actor)
        return next((item for item in resolved if item["id"] == alert_id), None)

    def list_alerts(self, *, state: str = "", severity: str = "", limit: int = 200) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if state:
            clauses.append("state=?")
            params.append(state)
        if severity:
            clauses.append("severity=?")
            params.append(severity)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(min(max(int(limit), 1), 1000))
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM alerts {where} ORDER BY last_seen_at DESC LIMIT ?",  # noqa: S608
                params,
            ).fetchall()
        return [self._alert(row) for row in rows]

    def dashboard(self) -> dict[str, Any]:
        with self.connect() as connection:
            counts = {
                str(row["state"]): int(row["count"])
                for row in connection.execute("SELECT state,COUNT(*) AS count FROM alerts GROUP BY state").fetchall()
            }
            pending = int(connection.execute("SELECT COUNT(*) FROM alert_deliveries WHERE state IN ('pending','retry')").fetchone()[0])
            failed = int(connection.execute("SELECT COUNT(*) FROM alert_deliveries WHERE state='failed'").fetchone()[0])
        return {"alerts": counts, "pending_deliveries": pending, "failed_deliveries": failed}

    def process_due_deliveries(self, limit: int = 20) -> dict[str, int]:
        now = time.time()
        with self._lock, self.connect() as connection:
            rows = connection.execute(
                """
                SELECT d.*,s.encrypted_config,s.type AS sink_type,s.name AS sink_name,s.enabled AS sink_enabled,
                       a.fingerprint,a.rule_id,a.source,a.event_key,a.title,a.object_ref,a.severity,a.state AS alert_state,
                       a.details_json,a.occurrences,a.first_seen_at,a.last_seen_at,a.last_notified_at,
                       a.acknowledged_at,a.acknowledged_by,a.acknowledgement_note,a.resolved_at,a.resolved_by
                FROM alert_deliveries d
                JOIN alert_sinks s ON s.id=d.sink_id
                JOIN alerts a ON a.id=d.alert_id
                WHERE d.state IN ('pending','retry') AND d.next_attempt_at<=?
                ORDER BY d.next_attempt_at,d.created_at
                LIMIT ?
                """,
                (now, min(max(int(limit), 1), 100)),
            ).fetchall()

        succeeded = 0
        retried = 0
        failed = 0
        for row in rows:
            delivery_id = str(row["id"])
            if not bool(row["sink_enabled"]):
                with self._lock, self.connect() as connection:
                    connection.execute("UPDATE alert_deliveries SET state='failed',last_error='sink disabled',updated_at=? WHERE id=?", (time.time(), delivery_id))
                failed += 1
                continue
            sink_row = {
                "id": str(row["sink_id"]),
                "name": str(row["sink_name"]),
                "type": str(row["sink_type"]),
                "encrypted_config": str(row["encrypted_config"]),
            }
            try:
                raw = self.cipher.decrypt(
                    sink_row["encrypted_config"],
                    associated_data=f"alert-sink:{sink_row['id']}",
                )
                config = json.loads(raw)
                if not isinstance(config, dict):
                    raise ValueError("invalid sink configuration")
                sink = {"id": sink_row["id"], "name": sink_row["name"], "type": sink_row["type"], **config}
                alert = {
                    "id": str(row["alert_id"]),
                    "fingerprint": str(row["fingerprint"]),
                    "source": str(row["source"]),
                    "title": str(row["title"]),
                    "object_ref": str(row["object_ref"]),
                    "severity": str(row["severity"]),
                    "state": str(row["alert_state"]),
                    "details": _loads(str(row["details_json"]), {}),
                    "first_seen_at": float(row["first_seen_at"]),
                    "last_seen_at": float(row["last_seen_at"]),
                }
                deliver(sink, alert)
            except (DeliveryError, OSError, ValueError, json.JSONDecodeError) as error:
                attempts = int(row["attempt_count"]) + 1
                max_attempts = int(row["max_attempts"])
                terminal = attempts >= max_attempts
                delay = min(30 * (2 ** max(attempts - 1, 0)), 900)
                safe_error = redact_text(type(error).__name__, limit=500)
                with self._lock, self.connect() as connection:
                    connection.execute(
                        "UPDATE alert_deliveries SET state=?,attempt_count=?,next_attempt_at=?,last_error=?,updated_at=? WHERE id=?",
                        ("failed" if terminal else "retry", attempts, time.time() + delay, safe_error, time.time(), delivery_id),
                    )
                if terminal:
                    failed += 1
                else:
                    retried += 1
                continue
            with self._lock, self.connect() as connection:
                connection.execute(
                    "UPDATE alert_deliveries SET state='succeeded',attempt_count=attempt_count+1,last_error='',updated_at=? WHERE id=?",
                    (time.time(), delivery_id),
                )
            succeeded += 1
        return {"processed": len(rows), "succeeded": succeeded, "retry": retried, "failed": failed}

    def test_delivery(self, sink_id: str, diagnostic: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM alert_sinks WHERE id=?", (sink_id,)).fetchone()
        if row is None:
            raise KeyError("notification sink not found")
        sink = self._decrypt_sink(row)
        deliver(
            sink,
            {
                "id": "test",
                "fingerprint": "test",
                "state": AlertState.firing.value,
                "severity": AlertSeverity.info.value,
                "source": "alert.test",
                "title": "WebNAS Alert Manager test delivery",
                "object_ref": sink_id,
                "details": redact(diagnostic),
                "first_seen_at": time.time(),
                "last_seen_at": time.time(),
            },
        )
        return {"ok": True, "sink_id": sink_id, "diagnostic": redact(diagnostic)}


_service: AlertService | None = None
_service_path = ""
_service_lock = threading.Lock()


def service() -> AlertService:
    global _service, _service_path
    path = str(Path(get_config().paths.data_dir) / "alerts" / "alerts.sqlite3")
    with _service_lock:
        if _service is None or _service_path != path:
            _service = AlertService(Path(path))
            _service_path = path
        return _service
