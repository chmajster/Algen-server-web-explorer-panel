from __future__ import annotations

import json
import sqlite3
import time
from functools import lru_cache
from typing import Any

from .service import HostRegistryService as BaseHostRegistryService


_LATEST_HOST_ROWS = {
    "facts": "updated_at",
    "host_agents": "updated_at",
    "host_reports": "created_at",
    "host_identity_salts": "generated_at",
}


class HostRegistryService(BaseHostRegistryService):
    """Host registry with page-level enrichment instead of per-host database reads."""

    def list_hosts(
        self,
        *,
        active_only: bool = False,
        search: str = "",
        status: str = "",
        tag: str = "",
        group_id: str = "",
        environment: str = "",
        location: str = "",
        limit: int = 5000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if active_only:
            clauses.append("active=1")
        for column, value in (
            ("connection_status", status),
            ("environment", environment),
            ("location", location),
        ):
            if value:
                clauses.append(f"{column}=?")
                values.append(value)
        if search:
            clauses.append("(name LIKE ? OR address LIKE ? OR hostname LIKE ? OR fqdn LIKE ?)")
            values.extend([f"%{search}%"] * 4)
        items = self._list(
            "hosts",
            where=" AND ".join(clauses),
            values=tuple(values),
            order="name",
            limit=min(limit + offset, 5000),
        )[offset:]
        if tag:
            items = [item for item in items if tag in item.get("tags", [])]
        if group_id:
            members = {
                item["host_id"]
                for item in self._list("memberships", where="group_id=?", values=(group_id,))
            }
            items = [item for item in items if item["id"] in members]
        return self._enrich_hosts(items)

    def active_hosts(self) -> list[dict[str, Any]]:
        return self.list_hosts(active_only=True)

    def host(self, host_id: str) -> dict[str, Any] | None:
        item = self._get("hosts", host_id)
        if not item:
            return None
        return self._enrich_hosts([item])[0]

    def _enrich_host(self, item: dict[str, Any]) -> dict[str, Any]:
        return self._enrich_hosts([item])[0]

    def _latest_host_rows_locked(
        self,
        connection: sqlite3.Connection,
        table: str,
        host_ids_json: str,
    ) -> dict[str, dict[str, Any]]:
        order_column = _LATEST_HOST_ROWS.get(table)
        if order_column is None:
            raise ValueError("unsupported host enrichment table")
        rows = connection.execute(
            f"""
            WITH selected(host_id) AS (
                SELECT CAST(value AS TEXT) FROM json_each(?)
            ), ranked AS (
                SELECT source.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY source.host_id
                           ORDER BY source.{order_column} DESC
                       ) AS __webnas_row_number
                FROM {table} AS source
                JOIN selected ON selected.host_id=source.host_id
            )
            SELECT * FROM ranked WHERE __webnas_row_number=1
            """,
            (host_ids_json,),
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = self._decode(row) or {}
            item.pop("__webnas_row_number", None)
            result[str(item["host_id"])] = item
        return result

    def _enrich_hosts(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items:
            return []

        host_ids = [str(item["id"]) for item in items]
        host_ids_json = json.dumps(host_ids, separators=(",", ":"))
        now = time.time()

        with self._lock, self.connect() as connection:
            group_rows = connection.execute(
                """
                WITH selected(host_id) AS (
                    SELECT CAST(value AS TEXT) FROM json_each(?)
                )
                SELECT memberships.host_id, groups.id, groups.name
                FROM memberships
                JOIN selected ON selected.host_id=memberships.host_id
                JOIN groups ON groups.id=memberships.group_id
                ORDER BY groups.name
                """,
                (host_ids_json,),
            ).fetchall()
            groups_by_host: dict[str, list[dict[str, str]]] = {host_id: [] for host_id in host_ids}
            for row in group_rows:
                groups_by_host.setdefault(str(row["host_id"]), []).append(
                    {"id": str(row["id"]), "name": str(row["name"])}
                )

            facts_by_host = self._latest_host_rows_locked(connection, "facts", host_ids_json)
            agents_by_host = self._latest_host_rows_locked(connection, "host_agents", host_ids_json)
            reports_by_host = self._latest_host_rows_locked(connection, "host_reports", host_ids_json)
            identities_by_host = self._latest_host_rows_locked(
                connection,
                "host_identity_salts",
                host_ids_json,
            )

            environment_rows = connection.execute("SELECT * FROM environments").fetchall()
            environments_by_ref: dict[str, dict[str, Any]] = {}
            environments = [self._decode(row) or {} for row in environment_rows]
            for environment_item in environments:
                slug = str(environment_item.get("slug") or "")
                if slug:
                    environments_by_ref[slug] = environment_item
            for environment_item in environments:
                environment_id = str(environment_item.get("id") or "")
                if environment_id:
                    environments_by_ref[environment_id] = environment_item

            credential_ids = list(
                dict.fromkeys(
                    str(item.get("credential_id") or "")
                    for item in items
                    if item.get("credential_id")
                )
            )
            credentials_by_id: dict[str, dict[str, Any]] = {}
            if credential_ids:
                credential_rows = connection.execute(
                    "SELECT * FROM credentials "
                    "WHERE id IN (SELECT CAST(value AS TEXT) FROM json_each(?))",
                    (json.dumps(credential_ids, separators=(",", ":")),),
                ).fetchall()
                for row in credential_rows:
                    credential = self._decode(row) or {}
                    credentials_by_id[str(credential["id"])] = self._credential_metadata(credential)

            setting = connection.execute(
                "SELECT value_json FROM hosts_manager_settings WHERE key=?",
                ("heartbeat_interval_seconds",),
            ).fetchone()
            heartbeat_interval = int(json.loads(setting["value_json"])) if setting else 30

        enriched: list[dict[str, Any]] = []
        for source_item in items:
            item = dict(source_item)
            host_id = str(item["id"])
            groups = groups_by_host.get(host_id, [])
            item["groups"] = groups
            item["group_ids"] = [group["id"] for group in groups]

            facts_record = facts_by_host.get(host_id)
            item["facts"] = facts_record.get("facts", {}) if facts_record else {}

            agent_record = agents_by_host.get(host_id)
            agent = (
                {key: value for key, value in agent_record.items() if key != "token_hash"}
                if agent_record
                else None
            )
            if agent:
                last_heartbeat = float(agent.get("last_heartbeat_at") or 0)
                if last_heartbeat and now - last_heartbeat > max(heartbeat_interval * 3, 60):
                    agent["status"] = "offline"
                    item["connection_status"] = "offline"
                elif agent.get("status") in {"online", "warning", "error"}:
                    item["connection_status"] = str(agent["status"])
            item["agent"] = agent
            item["agent_status"] = str(agent["status"]) if agent else "not_installed"

            report_record = reports_by_host.get(host_id)
            report = report_record.get("report", {}) if report_record else {}
            item["latest_report"] = report

            identity = identities_by_host.get(host_id)
            item["identity"] = (
                {key: value for key, value in identity.items() if key != "salt"}
                if identity
                else None
            )

            environment_ref = str(item.get("environment") or "")
            item["environment_details"] = environments_by_ref.get(environment_ref) if environment_ref else None

            basic = report.get("basic", {}) if isinstance(report, dict) else {}
            packages = report.get("packages", {}) if isinstance(report, dict) else {}
            item["distribution"] = basic.get("distribution") or item["facts"].get("distribution", "")
            item["system_version"] = basic.get("system_version") or item["facts"].get(
                "distribution_version",
                "",
            )
            item["agent_version"] = (agent or {}).get("agent_version", "")
            item["available_updates"] = int(packages.get("available_updates_count") or 0)
            item["security_updates"] = int(packages.get("security_updates_count") or 0)

            if not item.get("active"):
                item["status"] = "disabled"
            elif not item.get("approved"):
                item["status"] = "pending"
            elif item["agent_status"] == "not_installed":
                item["status"] = "unregistered"
            elif item["agent_status"] in {"warning", "error", "offline", "online"}:
                item["status"] = item["agent_status"]
            else:
                item["status"] = str(item.get("registration_status") or "pending")

            credential_id = str(item.get("credential_id") or "")
            item["credential"] = credentials_by_id.get(credential_id) if credential_id else None
            enriched.append(item)

        return enriched


@lru_cache
def registry() -> HostRegistryService:
    return HostRegistryService()
