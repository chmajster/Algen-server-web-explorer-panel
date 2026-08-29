from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from ...alerts.models import AlertEvent, AlertSeverity
from ...alerts.service import service as alerts

_ACCEPT_RE = re.compile(r"Accepted\s+(?P<method>\S+)\s+for\s+(?P<user>\S+)\s+from\s+(?P<ip>\S+)", re.I)
_FAILED_RE = re.compile(r"Failed\s+(?P<method>\S+)\s+for\s+(?:invalid user\s+)?(?P<user>\S+)\s+from\s+(?P<ip>\S+)", re.I)
_PAM_SESSION_RE = re.compile(r"pam_unix\([^:]+:session\):\s+session\s+(?P<action>opened|closed)\s+for user\s+(?P<user>\S+)", re.I)
_SUDO_RE = re.compile(r"^(?P<user>\S+)\s*:\s+.*COMMAND=", re.I)


class LoginHistoryUnavailable(RuntimeError):
    pass


class LoginHistoryService:
    def _run(self, args: list[str], *, timeout: int = 20) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False, shell=False)

    def _journal(self, *, since: str = "24 hours ago", limit: int = 1000) -> list[dict[str, Any]]:
        binary = shutil.which("journalctl")
        if not binary:
            raise LoginHistoryUnavailable("journalctl is unavailable")
        result = self._run([binary, "--no-pager", "-o", "json", "--since", since, "-n", str(min(max(limit, 1), 10000)), "_COMM=sshd", "+", "SYSLOG_IDENTIFIER=sshd"], timeout=30)
        if result.returncode not in {0, 1}:
            raise LoginHistoryUnavailable((result.stderr or "journalctl failed")[:500])
        rows: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
        return rows

    @staticmethod
    def _timestamp(row: dict[str, Any]) -> float:
        raw = str(row.get("__REALTIME_TIMESTAMP") or "")
        if raw.isdigit():
            return int(raw) / 1_000_000
        return time.time()

    def parse_row(self, row: dict[str, Any]) -> dict[str, Any] | None:
        message = str(row.get("MESSAGE") or "")
        base = {"timestamp": self._timestamp(row), "hostname": str(row.get("_HOSTNAME") or ""), "raw": message[:1000]}
        match = _ACCEPT_RE.search(message)
        if match:
            return {**base, "username": match.group("user"), "source_ip": match.group("ip"), "authentication_method": match.group("method"), "session_type": "ssh", "result": "success", "event": "login", "session_id": "", "terminal": "", "duration": None}
        match = _FAILED_RE.search(message)
        if match:
            return {**base, "username": match.group("user"), "source_ip": match.group("ip"), "authentication_method": match.group("method"), "session_type": "ssh", "result": "failure", "event": "login", "session_id": "", "terminal": "", "duration": None}
        match = _PAM_SESSION_RE.search(message)
        if match:
            return {**base, "username": match.group("user"), "source_ip": "", "authentication_method": "pam", "session_type": "local", "result": "success", "event": "login" if match.group("action").lower() == "opened" else "logout", "session_id": "", "terminal": "", "duration": None}
        match = _SUDO_RE.search(message)
        if "sudo" in str(row.get("SYSLOG_IDENTIFIER") or "").lower() and match:
            return {**base, "username": match.group("user"), "source_ip": "", "authentication_method": "sudo/pam", "session_type": "local", "result": "success", "event": "sudo", "session_id": "", "terminal": "", "duration": None}
        return None

    def events(self, *, limit: int = 100, offset: int = 0, username: str = "", source_ip: str = "", result: str = "", session_type: str = "", query: str = "", since: str = "7 days ago") -> dict[str, Any]:
        fetch_limit = min(10000, max((offset + limit) * 4, 1000))
        events = [event for row in self._journal(since=since, limit=fetch_limit) if (event := self.parse_row(row))]
        if username:
            events = [item for item in events if item["username"] == username]
        if source_ip:
            events = [item for item in events if item["source_ip"] == source_ip]
        if result:
            events = [item for item in events if item["result"] == result]
        if session_type:
            events = [item for item in events if item["session_type"] == session_type]
        if query:
            needle = query.casefold()
            events = [item for item in events if needle in " ".join(str(item.get(key, "")) for key in ("username", "source_ip", "authentication_method", "raw")).casefold()]
        events.sort(key=lambda item: item["timestamp"], reverse=True)
        total = len(events)
        safe_limit, safe_offset = min(max(limit, 1), 500), max(offset, 0)
        return {"items": events[safe_offset:safe_offset + safe_limit], "total": total, "limit": safe_limit, "offset": safe_offset}

    def active_sessions(self) -> list[dict[str, Any]]:
        binary = shutil.which("loginctl")
        if binary:
            result = self._run([binary, "list-sessions", "--no-legend", "--no-pager"], timeout=10)
            sessions: list[dict[str, Any]] = []
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) < 3:
                    continue
                session_id, uid, user = parts[:3]
                detail = self._run([binary, "show-session", session_id, "--property=Name,Remote,RemoteHost,TTY,Timestamp,State", "--value"], timeout=8)
                values = detail.stdout.splitlines()
                sessions.append({"session_id": session_id, "uid": uid, "user": user, "remote": values[1].strip().lower() == "yes" if len(values) > 1 else False, "remote_ip": values[2].strip() if len(values) > 2 else "", "terminal": values[3].strip() if len(values) > 3 else "", "login_time": values[4].strip() if len(values) > 4 else "", "state": values[5].strip() if len(values) > 5 else "unknown"})
            return sessions
        who = shutil.which("who")
        if not who:
            return []
        result = self._run([who, "-u"], timeout=10)
        sessions = []
        for index, line in enumerate(result.stdout.splitlines()):
            parts = line.split()
            if len(parts) >= 4:
                sessions.append({"session_id": f"who-{index}", "user": parts[0], "terminal": parts[1], "login_time": " ".join(parts[2:4]), "remote_ip": parts[-1].strip("()") if parts[-1].startswith("(") else "", "state": "active"})
        return sessions

    def terminate_session(self, session_id: str) -> dict[str, Any]:
        binary = shutil.which("loginctl")
        if not binary:
            raise LoginHistoryUnavailable("loginctl is unavailable; active session termination is unsupported")
        result = self._run([binary, "terminate-session", session_id], timeout=20)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "session termination failed")[:500])
        return {"session_id": session_id, "terminated": True}

    def security_findings(self, *, minutes: int = 5, brute_force_threshold: int = 20, spray_users: int = 5) -> list[dict[str, Any]]:
        events = self.events(limit=5000, offset=0, result="failure", since=f"{max(minutes, 1)} minutes ago")["items"]
        by_ip: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            if event["source_ip"]:
                by_ip[event["source_ip"]].append(event)
            if event["username"]:
                by_user[event["username"]].append(event)
        findings: list[dict[str, Any]] = []
        for address, rows in by_ip.items():
            users = {row["username"] for row in rows}
            if len(rows) >= brute_force_threshold:
                findings.append({"type": "brute_force", "source_ip": address, "count": len(rows), "users": sorted(users)[:20], "severity": "error"})
            if len(users) >= spray_users:
                findings.append({"type": "password_spray", "source_ip": address, "count": len(rows), "users": sorted(users)[:20], "severity": "warning"})
        for user, rows in by_user.items():
            if len(rows) >= brute_force_threshold:
                findings.append({"type": "targeted_account", "username": user, "count": len(rows), "severity": "warning"})
        return findings

    def emit_findings(self) -> list[dict[str, Any]]:
        findings = self.security_findings()
        for finding in findings:
            key = f"{finding['type']}:{finding.get('source_ip') or finding.get('username') or 'unknown'}"
            try:
                alerts().fire(AlertEvent(source="login-history", key=key, title=f"Login security event: {finding['type'].replace('_', ' ')}", object_ref=str(finding.get("source_ip") or finding.get("username") or ""), details=finding, severity=AlertSeverity.error if finding["severity"] == "error" else AlertSeverity.warning))
            except Exception:  # noqa: BLE001 - alerting must not break history view
                pass
        return findings

    def overview(self) -> dict[str, Any]:
        recent = self.events(limit=5000, result="", since="24 hours ago")["items"]
        success = [item for item in recent if item["result"] == "success" and item["event"] == "login"]
        failed = [item for item in recent if item["result"] == "failure"]
        accounts = Counter(item["username"] for item in failed if item["username"])
        findings = self.emit_findings()
        return {"successful_logins_24h": len(success), "failed_logins_24h": len(failed), "unique_source_ips": len({item["source_ip"] for item in recent if item["source_ip"]}), "active_sessions": len(self.active_sessions()), "most_attacked_account": accounts.most_common(1)[0][0] if accounts else "", "findings": findings}


_instance: LoginHistoryService | None = None


def service() -> LoginHistoryService:
    global _instance
    if _instance is None:
        _instance = LoginHistoryService()
    return _instance
