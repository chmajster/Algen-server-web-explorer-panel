"""Supported cross-module API for Ansible Controller."""

from .awx import AwxClient
from .backup import create_backup, delete_backup, list_backups, restore_backup
from .inventory import generate_inventory, inventory_records, parse_inventory
from .models import (
    MANAGED_SSH_USERNAME, PROTECTED_MANAGED_USERNAMES, AwxSettingsInput, CredentialInput,
    CredentialType, HostInput, NetworkScanInput,
)
from .network import build_nmap_args, parse_nmap_xml, scan_addresses
from .repository import repository
from .runner import (
    SSH_COMMANDS, build_ssh_args, controller_identity, demote_preexec, execute_ad_hoc,
    execute_template, execution_directory, fingerprint_key, keyscan_args, parse_keyscan,
    run_remote_user_setup,
)
from .security import atomic_private_write, redact_text

__all__ = [
    "AwxClient", "AwxSettingsInput", "CredentialInput", "CredentialType", "HostInput",
    "MANAGED_SSH_USERNAME", "NetworkScanInput", "PROTECTED_MANAGED_USERNAMES", "SSH_COMMANDS",
    "atomic_private_write", "build_nmap_args", "build_ssh_args", "controller_identity", "create_backup",
    "delete_backup", "demote_preexec", "execute_ad_hoc", "execute_template", "execution_directory",
    "fingerprint_key", "generate_inventory", "inventory_records", "keyscan_args", "list_backups",
    "parse_inventory", "parse_keyscan", "parse_nmap_xml", "redact_text", "repository", "restore_backup",
    "run_remote_user_setup", "scan_addresses",
]
