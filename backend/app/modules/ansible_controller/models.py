from __future__ import annotations

import ipaddress
import json
import re
from enum import StrEnum
from typing import Any, Annotated, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,127}$")]
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
MANAGED_SSH_USERNAME = "algen-ansible"
PROTECTED_MANAGED_USERNAMES = {"root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail", "news", "uucp", "proxy", "www-data", "backup", "list", "irc", "gnats", "nobody", "systemd-network", "systemd-resolve", "messagebus", "_apt", "sshd"}


def validate_managed_username(value: str) -> str:
    if value.casefold() in PROTECTED_MANAGED_USERNAMES:
        raise ValueError("a protected system account cannot be used for Ansible automation")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CredentialType(StrEnum):
    ssh_private_key = "ssh_private_key"
    ssh_password = "ssh_password"
    become_password = "become_password"
    git_private_key = "git_private_key"
    awx_token = "awx_token"
    vault_secret = "vault_secret"


class ConnectionType(StrEnum):
    ssh = "ssh"
    paramiko = "paramiko"


class ScanMethod(StrEnum):
    tcp = "tcp"
    nmap = "nmap"


class ConcurrencyPolicy(StrEnum):
    parallel = "parallel"
    same_hosts = "same_hosts"
    template = "template"
    single = "single"


class ScheduleKind(StrEnum):
    once = "once"
    hourly = "hourly"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    cron = "cron"


class HostInput(StrictModel):
    name: Name
    address: str = Field(min_length=1, max_length=253)
    port: int = Field(default=22, ge=1, le=65535)
    ssh_user: str = Field(default="algen-ansible", min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
    credential_id: str | None = Field(default=None, max_length=64, pattern=r"^[a-f0-9]{24,64}$")
    python_interpreter: str = Field(default="auto_silent", max_length=255)
    connection_type: ConnectionType = ConnectionType.ssh
    environment: str = Field(default="", max_length=64)
    location: str = Field(default="", max_length=128)
    tags: list[str] = Field(default_factory=list, max_length=50)
    variables: dict[str, Any] = Field(default_factory=dict)
    active: bool = True

    @field_validator("address")
    @classmethod
    def safe_address(cls, value: str) -> str:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            address = None
        if address is not None:
            if address.is_loopback or address.is_unspecified or address.is_multicast:
                raise ValueError("the controller host cannot be an automation target")
            return value
        try:
            ascii_value = value.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise ValueError("invalid host address") from error
        labels = ascii_value.rstrip(".").split(".")
        if ascii_value.rstrip(".").casefold() == "localhost" or not labels or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in labels):
            raise ValueError("invalid host address")
        return ascii_value.rstrip(".")

    @field_validator("python_interpreter")
    @classmethod
    def safe_python_interpreter(cls, value: str) -> str:
        if value in {"auto", "auto_silent"} or re.fullmatch(r"/(?:usr|opt)/[A-Za-z0-9_./-]{1,240}", value) and ".." not in value:
            return value
        raise ValueError("Python interpreter must be auto or a safe absolute /usr or /opt path")

    @field_validator("address")
    @classmethod
    def valid_address(cls, value: str) -> str:
        value = value.strip().rstrip(".")
        try:
            ipaddress.ip_address(value)
        except ValueError:
            if not re.fullmatch(r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", value):
                raise ValueError("invalid host address")
        return value

    @field_validator("python_interpreter")
    @classmethod
    def safe_interpreter(cls, value: str) -> str:
        if value not in {"auto", "auto_silent", "/usr/bin/python3", "/usr/local/bin/python3"}:
            raise ValueError("unsupported Python interpreter")
        return value

    @field_validator("tags")
    @classmethod
    def safe_tags(cls, value: list[str]) -> list[str]:
        if any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", item) for item in value):
            raise ValueError("invalid host tag")
        return list(dict.fromkeys(value))

    @field_validator("variables")
    @classmethod
    def no_secret_variables(cls, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, ensure_ascii=False)
        if len(encoded.encode()) > 128 * 1024:
            raise ValueError("host variables exceed 128 KiB")

        def validate(nested: Any) -> None:
            if isinstance(nested, dict):
                for raw_key, child in nested.items():
                    key = str(raw_key).casefold()
                    if any(marker in key for marker in ("password", "passwd", "private_key", "token", "secret", "vault")):
                        raise ValueError("secrets must be stored as credentials")
                    if key.startswith("ansible_") or key in {"connection", "delegate_to", "local_action"}:
                        raise ValueError("connection and Ansible transport variables use dedicated validated fields")
                    validate(child)
            elif isinstance(nested, list):
                for child in nested:
                    validate(child)

        validate(value)
        return value


class EnrollmentTokenInput(StrictModel):
    hostname_pattern: str = Field(default="node-*", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9*?.-]+$")
    ssh_user: str = Field(default=MANAGED_SSH_USERNAME, min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
    port: int = Field(default=22, ge=1, le=65535)
    credential_id: str | None = Field(default=None, max_length=64, pattern=r"^[a-f0-9]{24,64}$")
    environment: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_.-]{0,64}$")
    location: str = Field(default="", max_length=128)
    tags: list[str] = Field(default_factory=list, max_length=50)
    expires_minutes: int = Field(default=15, ge=5, le=60)

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, value: list[str]) -> list[str]:
        return HostInput.safe_tags(value)


class EnrollmentClaimInput(StrictModel):
    hostname: str = Field(min_length=1, max_length=128, pattern=r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
    address: str = Field(min_length=1, max_length=253)


class GroupInput(StrictModel):
    name: Identifier
    description: str = Field(default="", max_length=500)
    parent_id: str | None = Field(default=None, max_length=64, pattern=r"^[a-f0-9]{24,64}$")
    variables: dict[str, Any] = Field(default_factory=dict)
    host_ids: list[str] = Field(default_factory=list, max_length=5000)
    active: bool = True

    @field_validator("variables")
    @classmethod
    def _validate_variables(cls, value: dict[str, Any]) -> dict[str, Any]:
        return HostInput.no_secret_variables(value)


class CredentialInput(StrictModel):
    name: Name
    type: CredentialType
    username: str = Field(default="", max_length=128)
    secret: str = Field(min_length=1, max_length=131072)
    description: str = Field(default="", max_length=500)
    passphrase: str = Field(default="", max_length=4096)
    confirm: bool = False

    @model_validator(mode="after")
    def validate_secret_shape(self) -> "CredentialInput":
        if self.type == CredentialType.ssh_password and not self.username:
            raise ValueError("SSH password credentials require a username")
        if self.type in {CredentialType.ssh_private_key, CredentialType.git_private_key}:
            if not re.fullmatch(r"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=\r\n]+\r?\n-----END (?:OPENSSH |RSA |EC )?PRIVATE KEY-----\r?\n?", self.secret):
                raise ValueError("private-key credentials require a PEM or OpenSSH private key")
        elif "\n" in self.secret or "\r" in self.secret:
            raise ValueError("password and token credentials must be a single line")
        if self.passphrase and self.type not in {CredentialType.ssh_private_key, CredentialType.git_private_key}:
            raise ValueError("a passphrase is valid only for private-key credentials")
        return self


class NetworkScanInput(StrictModel):
    cidr: str | None = Field(default=None, max_length=64)
    start_address: str | None = Field(default=None, max_length=64)
    end_address: str | None = Field(default=None, max_length=64)
    port: int = Field(default=22, ge=1, le=65535)
    timeout_seconds: float = Field(default=2.0, ge=0.2, le=15)
    concurrency: int = Field(default=32, ge=1, le=128)
    group_name: str = Field(default="", max_length=64, pattern=r"^(?:[A-Za-z][A-Za-z0-9_-]{0,63})?$")
    method: ScanMethod = ScanMethod.nmap
    reverse_dns: bool = False
    confirm: bool = False

    @model_validator(mode="after")
    def exactly_one_range(self) -> "NetworkScanInput":
        if bool(self.cidr) == bool(self.start_address or self.end_address):
            raise ValueError("provide either CIDR or an address range")
        if bool(self.start_address) != bool(self.end_address):
            raise ValueError("both range endpoints are required")
        try:
            if self.cidr:
                network = ipaddress.ip_network(self.cidr, strict=False)
                if network.prefixlen == 0:
                    raise ValueError
            else:
                start = ipaddress.ip_address(self.start_address or "")
                end = ipaddress.ip_address(self.end_address or "")
                if start.version != end.version or int(start) > int(end):
                    raise ValueError
        except ValueError as error:
            raise ValueError("invalid scan CIDR or address range") from error
        return self


class ScanImportInput(StrictModel):
    host_ids: list[str] = Field(min_length=1, max_length=4096)
    group_name: str = Field(default="", max_length=64, pattern=r"^(?:[A-Za-z][A-Za-z0-9_-]{0,63})?$")
    confirm: bool = False


class FingerprintAcceptInput(StrictModel):
    fingerprint: str = Field(min_length=16, max_length=256, pattern=r"^(?:SHA256:[A-Za-z0-9+/=]{16,}|[A-Fa-f0-9:]{31,})$")
    public_key: str = Field(
        min_length=32,
        max_length=16384,
        pattern=r"^(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)) [A-Za-z0-9+/=]+$",
    )
    replace: bool = False
    confirm: bool = False


class OnboardingInput(StrictModel):
    host: HostInput
    initial_username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
    credential_id: str | None = Field(default=None, max_length=64, pattern=r"^[a-f0-9]{24,64}$")
    create_managed_user: Literal[True] = True
    managed_username: str = Field(default=MANAGED_SSH_USERNAME, min_length=2, max_length=32, pattern=r"^[a-z_][a-z0-9_-]{0,30}[a-z0-9_$]$")
    sudo_profile: str = Field(default="none", pattern=r"^(none|password|nopasswd|custom)$")
    sudoers_policy: str = Field(default="", max_length=8192)
    confirm: bool = False
    confirm_host_name: str = Field(default="", max_length=253)

    @field_validator("managed_username")
    @classmethod
    def safe_managed_username(cls, value: str) -> str:
        return validate_managed_username(value)

    @model_validator(mode="after")
    def dangerous_sudo_confirmation(self) -> "OnboardingInput":
        if self.sudo_profile == "nopasswd" and self.confirm_host_name != self.host.address:
            raise ValueError("full passwordless sudo requires typing the host address")
        if self.sudo_profile == "custom" and not self.sudoers_policy.strip():
            raise ValueError("custom sudo policy is required")
        return self

    @field_validator("sudoers_policy")
    @classmethod
    def safe_sudoers_policy(cls, value: str) -> str:
        if value and (not re.fullmatch(r"[A-Za-z0-9_./,=():!*%+@ -]{1,8192}", value) or any(marker in value for marker in ("..", "`", "$", "\n", "\r"))):
            raise ValueError("custom sudoers policy contains unsupported syntax")
        return value


class ProjectInput(StrictModel):
    name: Name
    source_type: str = Field(default="editor", pattern=r"^(editor|git|archive|managed_directory)$")
    repository_url: str | None = Field(default=None, max_length=2048)
    revision: str = Field(default="main", max_length=120, pattern=r"^[A-Za-z0-9_./-]{1,120}$")
    credential_id: str | None = Field(default=None, max_length=64, pattern=r"^[a-f0-9]{24,64}$")
    sync_before_run: bool = False
    allow_submodules: bool = False
    active: bool = True

    @field_validator("revision")
    @classmethod
    def safe_revision(cls, value: str) -> str:
        if ".." in value or value.startswith("/"):
            raise ValueError("unsafe Git revision")
        return value

    @field_validator("repository_url")
    @classmethod
    def safe_repository_url(cls, value: str | None) -> str | None:
        if not value:
            return None
        if any(marker in value for marker in ("\x00", "\r", "\n", "..")):
            raise ValueError("unsafe Git repository URL")
        if re.fullmatch(r"git@[A-Za-z0-9.-]{1,253}:[A-Za-z0-9_./~-]{1,1500}", value):
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "ssh"} or not parsed.hostname or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Git URL must use HTTPS or SSH without embedded secrets")
        if parsed.scheme == "https" and parsed.username:
            raise ValueError("HTTPS Git credentials must use the credential store")
        if parsed.scheme == "ssh" and parsed.username not in {None, "git"}:
            raise ValueError("SSH Git URLs may only use the git account")
        return value

    @model_validator(mode="after")
    def source_requirements(self) -> "ProjectInput":
        if self.source_type == "git" and not self.repository_url:
            raise ValueError("Git projects require a repository URL")
        if self.source_type != "git" and self.repository_url:
            raise ValueError("repository URL is only valid for Git projects")
        return self


class PlaybookInput(StrictModel):
    project_id: str = Field(max_length=64, pattern=r"^[a-f0-9]{24,64}$")
    name: Name
    filename: str = Field(max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,190}\.ya?ml$")
    content: str = Field(min_length=1, max_length=2_000_000)
    comment: str = Field(default="", max_length=500)
    active: bool = True


class TemplateInput(StrictModel):
    name: Name
    description: str = Field(default="", max_length=1000)
    project_id: str = Field(max_length=64, pattern=r"^[a-f0-9]{24,64}$")
    playbook_id: str = Field(max_length=64, pattern=r"^[a-f0-9]{24,64}$")
    host_ids: list[str] = Field(default_factory=list, max_length=5000)
    group_ids: list[str] = Field(default_factory=list, max_length=500)
    ssh_credential_id: str | None = Field(default=None, max_length=64)
    become_credential_id: str | None = Field(default=None, max_length=64)
    vault_credential_id: str | None = Field(default=None, max_length=64)
    limit: str = Field(default="", max_length=512, pattern=r"^[A-Za-z0-9_.,:&!*-]*$")
    tags: list[str] = Field(default_factory=list, max_length=100)
    skip_tags: list[str] = Field(default_factory=list, max_length=100)
    check_mode: bool = False
    diff_mode: bool = False
    verbosity: int = Field(default=0, ge=0, le=4)
    forks: int = Field(default=10, ge=1, le=100)
    timeout_seconds: int = Field(default=3600, ge=10, le=86400)
    extra_vars: str = Field(default="{}", max_length=256 * 1024)
    concurrency_policy: ConcurrencyPolicy = ConcurrencyPolicy.same_hosts
    sync_before_run: bool = False
    confirmation_required: bool = True
    active: bool = True

    @field_validator("extra_vars")
    @classmethod
    def safe_extra_vars(cls, value: str) -> str:
        try:
            parsed = yaml.safe_load(value) or {}
        except yaml.YAMLError as error:
            raise ValueError(f"invalid extra variables YAML: {error}") from error
        if not isinstance(parsed, dict):
            raise ValueError("extra variables must be a mapping")
        if any(marker in str(key).lower() for key in parsed for marker in ("password", "passwd", "secret", "token", "private_key", "vault")):
            raise ValueError("secrets must be supplied as credentials")
        return yaml.safe_dump(parsed, sort_keys=True)


class LaunchInput(StrictModel):
    confirm: bool = False
    check_mode: bool | None = None
    diff_mode: bool | None = None


class ScheduleInput(StrictModel):
    name: Name
    template_id: str = Field(max_length=64, pattern=r"^[a-f0-9]{24,64}$")
    kind: ScheduleKind
    expression: str = Field(min_length=1, max_length=120)
    timezone: str = Field(default="UTC", max_length=64, pattern=r"^[A-Za-z_]+(?:/[A-Za-z0-9_+.-]+)*$")
    missed_policy: str = Field(default="skip", pattern=r"^(skip|run_once)$")
    active: bool = True

    @model_validator(mode="after")
    def strict_expression(self) -> "ScheduleInput":
        if self.kind == ScheduleKind.once:
            from datetime import datetime

            try:
                datetime.fromisoformat(self.expression)
            except ValueError as error:
                raise ValueError("one-time schedule requires an ISO date and time") from error
        elif self.kind == ScheduleKind.cron:
            fields = self.expression.split()
            if any(char not in "0123456789*,-/ " for char in self.expression) or len(fields) != 5:
                raise ValueError("cron requires five strictly validated fields")
            for field, (minimum, maximum) in zip(fields, ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7)), strict=True):
                for part in field.split(","):
                    if part == "*":
                        continue
                    if part.startswith("*/") and part[2:].isdigit() and 1 <= int(part[2:]) <= maximum:
                        continue
                    match = re.fullmatch(r"(\d+)-(\d+)", part)
                    if match and minimum <= int(match.group(1)) <= int(match.group(2)) <= maximum:
                        continue
                    if part.isdigit() and minimum <= int(part) <= maximum:
                        continue
                    raise ValueError("cron field contains an invalid value or range")
        elif self.expression not in {"1", "default"}:
            if any(char not in "0123456789" for char in self.expression):
                raise ValueError("recurring schedule expression must be an interval")
        return self


class AwxSettingsInput(StrictModel):
    url: AnyHttpUrl
    credential_id: str | None = Field(default=None, max_length=64)
    verify_tls: bool = True
    ca_certificate: str = Field(default="", max_length=131072)
    timeout_seconds: int = Field(default=15, ge=2, le=120)

    @field_validator("url")
    @classmethod
    def require_https(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "https":
            raise ValueError("external AWX URL must use HTTPS")
        return value


class ConfirmationInput(StrictModel):
    confirm: bool = False


class ControllerConfigInput(StrictModel):
    allowed_networks: list[str] = Field(default_factory=list, max_length=100)
    max_scan_addresses: int = Field(default=4096, ge=1, le=4096)
    default_concurrency_policy: ConcurrencyPolicy = ConcurrencyPolicy.same_hosts
    managed_username: str = Field(default=MANAGED_SSH_USERNAME, min_length=2, max_length=32, pattern=r"^[a-z_][a-z0-9_-]{0,30}[a-z0-9_$]$")
    managed_sudo_profile: str = Field(default="none", pattern=r"^(none|nopasswd)$")
    managed_shell: str = Field(default="/bin/bash", pattern=r"^/bin/(?:ba)?sh$")
    managed_comment: str = Field(default="Algen Ansible automation", max_length=100, pattern=r"^[^:\r\n]*$")
    managed_authorized_keys_mode: str = Field(default="exclusive", pattern=r"^exclusive$")
    managed_key_rotation_days: int = Field(default=90, ge=0, le=365)
    awx: AwxSettingsInput | None = None
    confirm: bool = False

    @field_validator("managed_username")
    @classmethod
    def safe_managed_username(cls, value: str) -> str:
        return validate_managed_username(value)


class ManagedAccountConfigInput(StrictModel):
    username: str = Field(default=MANAGED_SSH_USERNAME, min_length=2, max_length=32, pattern=r"^[a-z_][a-z0-9_-]{0,30}[a-z0-9_$]$")
    sudo_profile: str = Field(default="none", pattern=r"^(none|nopasswd)$")
    shell: str = Field(default="/bin/bash", pattern=r"^/bin/(?:ba)?sh$")
    comment: str = Field(default="Algen Ansible automation", max_length=100, pattern=r"^[^:\r\n]*$")
    authorized_keys_mode: str = Field(default="exclusive", pattern=r"^exclusive$")
    key_rotation_days: int = Field(default=90, ge=0, le=365)
    confirm: bool = False

    @field_validator("username")
    @classmethod
    def safe_managed_username(cls, value: str) -> str:
        return validate_managed_username(value)


class InventoryImportInput(StrictModel):
    content: str = Field(min_length=1, max_length=2_000_000)
    format: str = Field(default="yaml", pattern=r"^(yaml|ini)$")
    confirm: bool = False


class BackupCreateInput(StrictModel):
    description: str = Field(default="", max_length=200)
    include_credentials: bool = False
    confirm: bool = False


class RestoreInput(StrictModel):
    checksum: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    include_credentials: bool = False
    confirm: bool = False
