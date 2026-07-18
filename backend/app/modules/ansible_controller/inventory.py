from __future__ import annotations

import configparser
import io
import re
from typing import Any

import yaml


SECRET_RE = re.compile(r"(?i)(ansible_(?:password|ssh_pass|become_pass|vault_password)|private_key|token|secret)")


def _assert_no_plaintext_secrets(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if SECRET_RE.search(str(key)):
                raise ValueError("inventory contains a plaintext secret")
            _assert_no_plaintext_secrets(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_plaintext_secrets(nested)


def generate_inventory(hosts: list[dict[str, Any]], groups: list[dict[str, Any]], memberships: list[dict[str, str]] | None = None) -> str:
    memberships = memberships or []
    host_by_id = {str(host["id"]): host for host in hosts if host.get("active", True)}
    children: dict[str, Any] = {}
    ungrouped: dict[str, Any] = {}
    by_group: dict[str, list[str]] = {}
    for membership in memberships:
        by_group.setdefault(str(membership["group_id"]), []).append(str(membership["host_id"]))
    for group in groups:
        if not group.get("active", True):
            continue
        name = str(group["name"])
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name):
            raise ValueError("invalid inventory group name")
        group_hosts: dict[str, Any] = {}
        for host_id in by_group.get(str(group["id"]), []):
            host = host_by_id.get(host_id)
            if host:
                group_hosts[str(host["name"])] = host_vars(host)
        children[name] = {"hosts": group_hosts, "vars": dict(group.get("variables") or {})}
    assigned = {host_id for values in by_group.values() for host_id in values}
    for host_id, host in host_by_id.items():
        if host_id not in assigned:
            ungrouped[str(host["name"])] = host_vars(host)
    payload = {"all": {"children": {**children, "ungrouped": {"hosts": ungrouped}}}}
    _assert_no_plaintext_secrets(payload)
    return yaml.safe_dump(payload, sort_keys=True, default_flow_style=False)


def host_vars(host: dict[str, Any]) -> dict[str, Any]:
    value = {
        **dict(host.get("variables") or {}),
        "ansible_host": host["address"],
        "ansible_port": int(host.get("port") or 22),
        "ansible_user": host.get("ssh_user") or "algen-ansible",
        "ansible_connection": host.get("connection_type") or "ssh",
        "ansible_python_interpreter": host.get("python_interpreter") or "auto_silent",
    }
    _assert_no_plaintext_secrets(value)
    return value


def parse_inventory(content: str, format_hint: str = "yaml", *, max_hosts: int = 5000) -> dict[str, Any]:
    if len(content.encode("utf-8")) > 2_000_000:
        raise ValueError("inventory exceeds 2 MiB")
    if format_hint == "ini":
        parser = configparser.ConfigParser(allow_no_value=True, delimiters=("=",))
        try:
            parser.read_file(io.StringIO(content))
        except configparser.Error as error:
            raise ValueError(f"invalid INI inventory: {error}") from error
        groups: dict[str, list[dict[str, str]]] = {}
        count = 0
        for section in parser.sections():
            name = section.split(":", 1)[0]
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name):
                raise ValueError("invalid inventory group name")
            items = []
            for raw, value in parser.items(section):
                if SECRET_RE.search(raw) or (value and SECRET_RE.search(value)):
                    raise ValueError("inventory contains a plaintext secret")
                items.append({"name": raw, "variables": value or ""})
                count += 1
            groups[name] = items
        if count > max_hosts:
            raise ValueError("inventory contains too many hosts")
        return {"format": "ini", "groups": groups, "host_count": count}
    try:
        value = yaml.safe_load(content) or {}
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML inventory: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("inventory must be a mapping")
    _assert_no_plaintext_secrets(value)
    def count_hosts(item: Any) -> int:
        if not isinstance(item, dict):
            return 0
        count = len(item.get("hosts") or {}) if isinstance(item.get("hosts"), dict) else 0
        children = item.get("children") or {}
        if isinstance(children, dict):
            count += sum(count_hosts(child) for child in children.values())
        return count

    host_count = count_hosts(value.get("all", value))
    if host_count > max_hosts:
        raise ValueError("inventory contains too many hosts")
    return {"format": "yaml", "inventory": value, "host_count": host_count}


def inventory_records(validation: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hosts: dict[str, dict[str, Any]] = {}
    groups: list[dict[str, Any]] = []
    if validation.get("format") == "ini":
        for group_name, entries in dict(validation.get("groups") or {}).items():
            names = []
            for entry in entries:
                name = str(entry["name"])
                hosts.setdefault(name, {"name": name, "address": name, "port": 22, "ssh_user": "algen-ansible", "variables": {}})
                names.append(name)
            groups.append({"name": group_name, "host_names": names, "variables": {}})
        return list(hosts.values()), groups
    root = dict(validation.get("inventory") or {})
    all_group = root.get("all", root)

    def visit(name: str, value: Any) -> None:
        if not isinstance(value, dict):
            return
        host_names: list[str] = []
        raw_hosts = value.get("hosts") or {}
        if isinstance(raw_hosts, dict):
            for host_name, raw_vars in raw_hosts.items():
                variables = dict(raw_vars or {}) if isinstance(raw_vars, dict) else {}
                record = hosts.setdefault(str(host_name), {"name": str(host_name), "address": str(host_name), "port": 22, "ssh_user": "algen-ansible", "variables": {}})
                record["address"] = str(variables.pop("ansible_host", record["address"]))
                record["port"] = int(variables.pop("ansible_port", record["port"]))
                record["ssh_user"] = str(variables.pop("ansible_user", record["ssh_user"]))
                record["python_interpreter"] = str(variables.pop("ansible_python_interpreter", "auto_silent"))
                record["connection_type"] = str(variables.pop("ansible_connection", "ssh"))
                record["variables"].update(variables)
                host_names.append(str(host_name))
        if name != "all":
            groups.append({"name": name, "host_names": host_names, "variables": dict(value.get("vars") or {})})
        children = value.get("children") or {}
        if isinstance(children, dict):
            for child_name, child in children.items():
                if child_name != "ungrouped":
                    visit(str(child_name), child)
                else:
                    visit("all", child)

    visit("all", all_group)
    return list(hosts.values()), groups


def validation_commands(inventory: str) -> list[list[str]]:
    """Return fixed ansible-inventory validation commands for a backend-owned path."""
    if not inventory or "\x00" in inventory:
        raise ValueError("invalid managed inventory path")
    return [
        ["ansible-inventory", "--inventory", inventory, "--list"],
        ["ansible-inventory", "--inventory", inventory, "--graph"],
    ]
