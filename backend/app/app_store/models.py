from __future__ import annotations

from pydantic import BaseModel, Field


class AdminAction(BaseModel):
    dry_run: bool = False


class SambaPassword(AdminAction):
    username: str
    password: str


class SambaShare(BaseModel):
    name: str
    path: str
    comment: str = ""
    enabled: bool = True
    browseable: bool = True
    hidden: bool = False
    read_only: bool = True
    guest_ok: bool = False
    valid_users: list[str] = Field(default_factory=list)
    valid_groups: list[str] = Field(default_factory=list)
    write_list: list[str] = Field(default_factory=list)
    read_list: list[str] = Field(default_factory=list)
    admin_users: list[str] = Field(default_factory=list)
    force_user: str | None = None
    force_group: str | None = None
    force_create_mode: str = ""
    force_directory_mode: str = ""
    inherit_permissions: bool = False
    veto_files: str = ""
    recycle_bin: bool = False
    recycle_versions: bool = True
    vfs_objects: list[str] = Field(default_factory=list)
    create_directory: bool = False
    directory_owner: str = ""
    directory_group: str = ""
    directory_mode: str = ""
    advanced_options: dict[str, str] = Field(default_factory=dict)
    create_mask: str = "0664"
    directory_mask: str = "0775"
    allow_proxmox_storage: bool = False


class SambaConfig(BaseModel):
    shares: list[SambaShare] = Field(default_factory=list)
    global_options: dict[str, str] = Field(default_factory=dict)


class SambaApplyRequest(BaseModel):
    config: SambaConfig | None = None


class SambaSecuredApplyRequest(AdminAction):
    config: SambaConfig
    confirm_smb1: bool = False


class SambaServiceAction(BaseModel):
    action: str


class SambaUserAction(AdminAction):
    username: str
