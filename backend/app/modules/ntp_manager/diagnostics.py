from __future__ import annotations

import re
import time
from typing import Any

from .models import NtpBackend

_CHRONY_SOURCE_RE = re.compile(
    r"^(?P<mode>[\^=#])(?P<state>[*+\-?x~])\s+"
    r"(?P<server>\S+)\s+(?P<stratum>\d+)\s+(?P<poll>\d+)\s+"
    r"(?P<reach>\d+)\s+(?P<last_rx>\S+)\s+(?P<sample>.+)$"
)
_DURATION_RE = re.compile(r"(?P<value>[+-]?\d+(?:\.\d+)?)\s*(?P<unit>ns|us|µs|ms|s|seconds?)?", re.IGNORECASE)

_CHRONY_STATE = {
    "*": "selected",
    "+": "candidate",
    "-": "outlier",
    "?": "unreachable",
    "x": "falseticker",
    "~": "jittery",
}
_CHRONY_MODE = {"^": "server", "=": "peer", "#": "reference-clock"}
_NTPQ_STATE = {
    "*": "selected",
    "+": "candidate",
    "-": "outlier",
    "x": "falseticker",
    ".": "excess",
    "o": "pps",
    "#": "backup",
}


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.search(r"[+-]?\d+(?:\.\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def duration_seconds(value: str | None) -> float | None:
    if not value:
        return None
    match = _DURATION_RE.search(value.strip())
    if not match:
        return None
    number = float(match.group("value"))
    unit = (match.group("unit") or "s").casefold()
    scale = {
        "ns": 1e-9,
        "us": 1e-6,
        "µs": 1e-6,
        "ms": 1e-3,
        "s": 1.0,
        "second": 1.0,
        "seconds": 1.0,
    }.get(unit, 1.0)
    return number * scale


def parse_key_values(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
        elif "=" in line:
            key, value = line.split("=", 1)
        else:
            continue
        result[key.strip().casefold()] = value.strip().strip('"')
    return result


def parse_chrony_sources(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = _CHRONY_SOURCE_RE.match(line)
        if not match:
            continue
        groups = match.groupdict()
        sample = groups["sample"]
        sample_match = re.match(r"(?P<offset>[+-]?\S+)(?:\[[^\]]+\])?\s+\+/-\s+(?P<uncertainty>\S+)", sample)
        state_code = groups["state"]
        item: dict[str, Any] = {
            "server": groups["server"],
            "selected": state_code == "*",
            "state": _CHRONY_STATE.get(state_code, state_code),
            "state_code": state_code,
            "mode": _CHRONY_MODE.get(groups["mode"], groups["mode"]),
            "stratum": int(groups["stratum"]),
            "poll": int(groups["poll"]),
            "reach": int(groups["reach"]),
            "last_rx": groups["last_rx"],
            "details": sample,
        }
        if sample_match:
            item["offset"] = sample_match.group("offset")
            item["offset_seconds"] = duration_seconds(item["offset"])
            item["uncertainty"] = sample_match.group("uncertainty")
        items.append(item)
    return items


def parse_chrony_sourcestats(text: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("Name/IP", "===")):
            continue
        parts = line.split()
        if len(parts) < 8:
            continue
        try:
            samples = int(parts[1])
            runs = int(parts[2])
            span = int(parts[3])
        except ValueError:
            continue
        result[parts[0]] = {
            "samples": samples,
            "runs": runs,
            "span_seconds": span,
            "frequency_ppm": _number(parts[4]),
            "frequency_skew_ppm": _number(parts[5]),
            "estimated_offset": parts[6],
            "std_dev": parts[7],
            "jitter": parts[7],
        }
    return result


def parse_ntpq_peers(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    markers = set(_NTPQ_STATE)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("remote", "====")):
            continue
        state_code = line[0] if line[0] in markers else ""
        payload = line[1:].strip() if state_code else line
        parts = payload.split()
        if len(parts) < 10:
            continue
        try:
            stratum = int(parts[2])
            poll = int(parts[5])
            reach = int(parts[6])
            delay_ms = float(parts[7])
            offset_ms = float(parts[8])
            jitter_ms = float(parts[9])
        except ValueError:
            continue
        items.append(
            {
                "server": parts[0],
                "reference": parts[1],
                "selected": state_code in {"*", "o"},
                "state": _NTPQ_STATE.get(state_code, "candidate"),
                "state_code": state_code or " ",
                "mode": parts[3],
                "stratum": stratum,
                "last_rx": parts[4],
                "poll": poll,
                "reach": reach,
                "delay": f"{delay_ms:g} ms",
                "delay_ms": delay_ms,
                "offset": f"{offset_ms:g} ms",
                "offset_seconds": offset_ms / 1000.0,
                "jitter": f"{jitter_ms:g} ms",
                "jitter_ms": jitter_ms,
            }
        )
    return items


def parse_ntpq_system(text: str) -> dict[str, str]:
    flattened = " ".join(line.strip() for line in text.splitlines())
    result: dict[str, str] = {}
    for part in flattened.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        result[key.strip().casefold()] = value.strip().strip('"')
    return result


def evaluate_health(status: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    if not status.get("available"):
        return "unavailable"
    if not status.get("synchronized"):
        return "unsynchronized"
    if status.get("service_state") not in {"active", "unknown", ""}:
        return "degraded"
    selected = [item for item in sources if item.get("selected")]
    if sources and not selected:
        return "degraded"
    offset_seconds = status.get("offset_seconds")
    if isinstance(offset_seconds, (int, float)) and abs(float(offset_seconds)) > 0.1:
        return "degraded"
    return "healthy"


def _merge_source_stats(sources: list[dict[str, Any]], stats: dict[str, dict[str, Any]]) -> None:
    for source in sources:
        server = str(source.get("server") or "")
        if server in stats:
            source.update(stats[server])


def collect_diagnostics(ntp_service: Any) -> dict[str, Any]:
    status = dict(ntp_service.status())
    backend = NtpBackend(status.get("backend", NtpBackend.none.value))
    sources = ntp_service.sources()
    metrics: dict[str, Any] = {}
    warnings: list[str] = []

    if backend == NtpBackend.chrony:
        chronyc = ntp_service._which("chronyc")
        if chronyc:
            tracking_result = ntp_service._run([chronyc, "tracking"], timeout=10)
            if tracking_result.returncode == 0:
                values = parse_key_values(tracking_result.stdout)
                stratum_text = values.get("stratum", "")
                stratum = int(stratum_text) if stratum_text.isdigit() else None
                offset = values.get("last offset", values.get("system time", ""))
                leap_status = values.get("leap status", "")
                metrics = {
                    "reference_id": values.get("reference id", ""),
                    "reference_time": values.get("reference time (utc)", values.get("reference time", "")),
                    "stratum": stratum,
                    "system_time": values.get("system time", ""),
                    "last_offset": values.get("last offset", ""),
                    "rms_offset": values.get("rms offset", ""),
                    "frequency": values.get("frequency", ""),
                    "residual_frequency": values.get("residual freq", ""),
                    "skew": values.get("skew", ""),
                    "root_delay": values.get("root delay", ""),
                    "root_dispersion": values.get("root dispersion", ""),
                    "update_interval": values.get("update interval", ""),
                    "leap_status": leap_status,
                }
                status.update(
                    {
                        "source": metrics["reference_id"],
                        "stratum": stratum,
                        "offset": offset,
                        "offset_seconds": duration_seconds(offset),
                        "jitter": metrics["root_dispersion"],
                        "root_delay": metrics["root_delay"],
                        "root_dispersion": metrics["root_dispersion"],
                        "frequency": metrics["frequency"],
                        "leap_status": leap_status,
                        "synchronized": bool(status.get("synchronized"))
                        or (stratum is not None and stratum > 0 and leap_status.casefold() == "normal"),
                    }
                )
            else:
                warnings.append("chronyc tracking failed")

            source_result = ntp_service._run([chronyc, "-n", "sources"], timeout=10)
            if source_result.returncode == 0:
                parsed_sources = parse_chrony_sources(source_result.stdout)
                if parsed_sources:
                    sources = parsed_sources
            else:
                warnings.append("chronyc sources failed")

            stats_result = ntp_service._run([chronyc, "-n", "sourcestats"], timeout=10)
            if stats_result.returncode == 0:
                _merge_source_stats(sources, parse_chrony_sourcestats(stats_result.stdout))
            else:
                warnings.append("chronyc sourcestats failed")

    elif backend == NtpBackend.timesyncd:
        timedatectl = ntp_service._which("timedatectl")
        if timedatectl:
            result = ntp_service._run([timedatectl, "show-timesync", "--all"], timeout=10)
            if result.returncode == 0:
                values = parse_key_values(result.stdout)
                server_name = values.get("servername", "")
                server_address = values.get("serveraddress", "")
                active_server = server_name or server_address
                metrics = {
                    "server_name": server_name,
                    "server_address": server_address,
                    "server_port": values.get("serverport", ""),
                    "poll_interval": values.get("pollintervalusec", ""),
                    "poll_interval_min": values.get("pollintervalminusec", ""),
                    "poll_interval_max": values.get("pollintervalmaxusec", ""),
                    "root_distance_max": values.get("rootdistancemaxusec", ""),
                    "frequency": values.get("frequency", ""),
                }
                if active_server:
                    status["source"] = active_server
                    matched = False
                    for source in sources:
                        if source.get("server") in {server_name, server_address}:
                            source["selected"] = True
                            source["state"] = "selected"
                            matched = True
                    if not matched:
                        sources.insert(
                            0,
                            {
                                "server": active_server,
                                "selected": True,
                                "state": "selected",
                                "mode": "server",
                                "address": server_address,
                            },
                        )
            else:
                warnings.append("timedatectl show-timesync failed")

    elif backend == NtpBackend.ntpd:
        ntpq = ntp_service._which("ntpq")
        if ntpq:
            peers_result = ntp_service._run([ntpq, "-pn"], timeout=10)
            if peers_result.returncode == 0:
                parsed_peers = parse_ntpq_peers(peers_result.stdout)
                if parsed_peers:
                    sources = parsed_peers
                    selected = next((item for item in sources if item.get("selected")), None)
                    if selected:
                        status["source"] = selected["server"]
                        status["stratum"] = selected["stratum"]
                        status["offset"] = selected["offset"]
                        status["offset_seconds"] = selected["offset_seconds"]
                        status["jitter"] = selected["jitter"]
            else:
                warnings.append("ntpq peers failed")

            rv_result = ntp_service._run([ntpq, "-c", "rv"], timeout=10)
            if rv_result.returncode == 0:
                values = parse_ntpq_system(rv_result.stdout)
                stratum_text = values.get("stratum", "")
                stratum = int(stratum_text) if stratum_text.isdigit() else status.get("stratum")
                leap = values.get("leap", "")
                offset_ms = _number(values.get("offset"))
                metrics = {
                    "reference_id": values.get("refid", ""),
                    "stratum": stratum,
                    "root_delay": values.get("rootdelay", ""),
                    "root_dispersion": values.get("rootdisp", ""),
                    "offset": values.get("offset", ""),
                    "frequency": values.get("frequency", ""),
                    "system_jitter": values.get("sys_jitter", ""),
                    "clock_wander": values.get("clk_wander", ""),
                    "leap": leap,
                }
                status.update(
                    {
                        "stratum": stratum,
                        "root_delay": metrics["root_delay"],
                        "root_dispersion": metrics["root_dispersion"],
                        "frequency": metrics["frequency"],
                        "leap_status": leap,
                        "synchronized": bool(status.get("synchronized"))
                        or (isinstance(stratum, int) and 0 < stratum < 16 and leap in {"00", ""}),
                    }
                )
                if offset_ms is not None:
                    status["offset"] = f"{offset_ms:g} ms"
                    status["offset_seconds"] = offset_ms / 1000.0
            else:
                warnings.append("ntpq rv failed")

    status.setdefault("offset_seconds", duration_seconds(str(status.get("offset") or "")))
    status.setdefault("root_delay", "")
    status.setdefault("root_dispersion", "")
    status.setdefault("frequency", "")
    status.setdefault("leap_status", "")

    health = evaluate_health(status, sources)
    selected_count = sum(1 for item in sources if item.get("selected"))
    reachable_count = sum(1 for item in sources if item.get("reach") not in {None, 0, "0"})
    return {
        "health": health,
        "status": status,
        "metrics": metrics,
        "sources": sources,
        "summary": {
            "source_count": len(sources),
            "selected_count": selected_count,
            "reachable_count": reachable_count,
        },
        "warnings": warnings,
        "collected_at": time.time(),
    }
