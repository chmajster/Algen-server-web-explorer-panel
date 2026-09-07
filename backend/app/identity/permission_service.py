from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from fastapi import HTTPException

from ..config import get_config
from ..security import SessionUser
from ..sqlite_utils import ClosingConnection
from .permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS

Effect = Literal["allow", "deny"]


@dataclass(frozen=True, slots=True)
class Resource:
    resource_type: str = "global"
    resource_id: str = "*"
    scope: str = "*"


@dataclass(frozen=True, slots=True)
class DecisionSource:
    effect: Effect
    permission: str
    source_type: str
    source_id: str
    source_name: str
    resource_type: str = "global"
    resource_id: str = "*"
    scope: str = "*"
    reason: str = ""


@dataclass(slots=True)
class PermissionDecision:
    allowed: bool
    permission: str
    resource: Resource
    sources: list[DecisionSource] = field(default_factory=list)
    reason: str = "default deny"

    def as_dict(self) -> dict[str, Any]:
        return {
            "result": "ALLOW" if self.allowed else "DENY",
            "permission": self.permission,
            "resource": asdict(self.resource),
            "reason": self.reason,
            "sources": [asdict(source) for source in self.sources],
        }


PERMISSION_ALIASES = {
    "desktop.read": "settings.view_own", "desktop.manage": "settings.edit_own",
    "files.write": "files.edit", "files.share": "files.download",
    "groups.read": "groups.view", "groups.update": "groups.manage_members",
    "roles.read": "access.view", "roles.create": "access.manage_roles",
    "roles.update": "access.manage_roles", "roles.delete": "access.manage_roles",
    "docker.read": "docker.view", "docker.manage": "docker.manage_containers",
    "services.read": "services.view", "services.manage": "services.restart",
    "system.read": "settings.view_system", "system.manage": "settings.edit_system",
    "settings.read": "settings.view_system", "settings.manage": "settings.edit_system",
    "rbac.read": "access.view", "rbac.manage": "access.manage_roles",
    "ldap.read": "access.view", "ldap.manage": "access.manage_roles",
    "audit.read": "audit.view_all",
}


def normalize_permission_id(permission: str) -> str:
    value = PERMISSION_ALIASES.get(permission.strip(), permission.strip())
    if value not in ALL_PERMISSIONS:
        raise HTTPException(422, f"Unknown permission: {permission}")
    return value


def _role_permissions(name: str) -> set[str]:
    for role, permissions in ROLE_PERMISSIONS.items():
        if str(getattr(role, "value", role)).casefold() == name.casefold():
            return set(permissions)
    return set()


SYSTEM_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "Administrator": set(ALL_PERMISSIONS),
    "Operator": _role_permissions("operator"),
    "Auditor": _role_permissions("auditor"),
    "User": _role_permissions("user"),
    "Read Only": {p for p in ALL_PERMISSIONS if p.endswith((".view", ".read", ".view_own"))},
}


class PermissionRepository:
    """Application-owned RBAC schema stored in the existing identity.sqlite3."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(get_config().paths.data_dir) / "identity.sqlite3"
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _initialize(self) -> None:
        with self._lock, self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS rbac_roles(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE COLLATE NOCASE,description TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1,role_type TEXT NOT NULL CHECK(role_type IN ('system','custom')),protected INTEGER NOT NULL DEFAULT 0,created_at REAL NOT NULL,created_by TEXT NOT NULL,updated_at REAL NOT NULL,updated_by TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS rbac_role_permissions(role_id TEXT NOT NULL REFERENCES rbac_roles(id) ON DELETE CASCADE,permission TEXT NOT NULL,effect TEXT NOT NULL CHECK(effect IN ('allow','deny')),resource_type TEXT NOT NULL DEFAULT 'global',resource_id TEXT NOT NULL DEFAULT '*',scope TEXT NOT NULL DEFAULT '*',PRIMARY KEY(role_id,permission,effect,resource_type,resource_id,scope));
            CREATE TABLE IF NOT EXISTS rbac_groups(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE COLLATE NOCASE,description TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1,source TEXT NOT NULL DEFAULT 'local',external_id TEXT NOT NULL DEFAULT '',distinguished_name TEXT NOT NULL DEFAULT '',managed INTEGER NOT NULL DEFAULT 0,created_at REAL NOT NULL,updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS rbac_group_members(group_id TEXT NOT NULL REFERENCES rbac_groups(id) ON DELETE CASCADE,provider TEXT NOT NULL,identity_id TEXT NOT NULL,username TEXT NOT NULL,PRIMARY KEY(group_id,provider,identity_id));
            CREATE TABLE IF NOT EXISTS rbac_group_roles(group_id TEXT NOT NULL REFERENCES rbac_groups(id) ON DELETE CASCADE,role_id TEXT NOT NULL REFERENCES rbac_roles(id) ON DELETE CASCADE,PRIMARY KEY(group_id,role_id));
            CREATE TABLE IF NOT EXISTS rbac_user_roles(provider TEXT NOT NULL,identity_id TEXT NOT NULL,username TEXT NOT NULL,role_id TEXT NOT NULL REFERENCES rbac_roles(id) ON DELETE CASCADE,created_at REAL NOT NULL,created_by TEXT NOT NULL,PRIMARY KEY(provider,identity_id,role_id));
            CREATE TABLE IF NOT EXISTS rbac_external_groups(id TEXT PRIMARY KEY,provider_id TEXT NOT NULL,external_id TEXT NOT NULL,distinguished_name TEXT NOT NULL,name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',parent_ids_json TEXT NOT NULL DEFAULT '[]',last_seen_at REAL NOT NULL DEFAULT 0,UNIQUE(provider_id,external_id));
            CREATE TABLE IF NOT EXISTS rbac_external_memberships(external_group_id TEXT NOT NULL REFERENCES rbac_external_groups(id) ON DELETE CASCADE,provider TEXT NOT NULL,identity_id TEXT NOT NULL,username TEXT NOT NULL,direct INTEGER NOT NULL DEFAULT 1,last_seen_at REAL NOT NULL,PRIMARY KEY(external_group_id,provider,identity_id));
            CREATE TABLE IF NOT EXISTS rbac_external_group_roles(external_group_id TEXT NOT NULL REFERENCES rbac_external_groups(id) ON DELETE CASCADE,role_id TEXT NOT NULL REFERENCES rbac_roles(id) ON DELETE CASCADE,PRIMARY KEY(external_group_id,role_id));
            CREATE TABLE IF NOT EXISTS rbac_policies(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE COLLATE NOCASE,description TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1,effect TEXT NOT NULL CHECK(effect IN ('allow','deny')),permission TEXT NOT NULL,resource_type TEXT NOT NULL DEFAULT 'global',resource_id TEXT NOT NULL DEFAULT '*',scope TEXT NOT NULL DEFAULT '*',conditions_json TEXT NOT NULL DEFAULT '{}',created_at REAL NOT NULL,created_by TEXT NOT NULL,updated_at REAL NOT NULL,updated_by TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS rbac_policy_subjects(policy_id TEXT NOT NULL REFERENCES rbac_policies(id) ON DELETE CASCADE,subject_type TEXT NOT NULL,subject_id TEXT NOT NULL,PRIMARY KEY(policy_id,subject_type,subject_id));
            CREATE TABLE IF NOT EXISTS rbac_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,actor TEXT NOT NULL,action TEXT NOT NULL,target TEXT NOT NULL,before_json TEXT NOT NULL DEFAULT '{}',after_json TEXT NOT NULL DEFAULT '{}',timestamp REAL NOT NULL,source_ip TEXT NOT NULL DEFAULT '');
            CREATE INDEX IF NOT EXISTS idx_rbac_group_members_identity ON rbac_group_members(provider,identity_id);
            CREATE INDEX IF NOT EXISTS idx_rbac_ext_members_identity ON rbac_external_memberships(provider,identity_id);
            CREATE INDEX IF NOT EXISTS idx_rbac_audit_time ON rbac_audit(timestamp DESC);
            """)
            now = time.time()
            for name, permissions in SYSTEM_ROLE_PERMISSIONS.items():
                role_id = f"system:{name.casefold().replace(' ', '-')}"
                db.execute("INSERT OR IGNORE INTO rbac_roles VALUES(?,?,?,?,?,?,?,?,?,?)", (role_id,name,f"WebNAS system role: {name}",1,"system",1,now,"migration",now,"migration"))
                for permission in permissions:
                    db.execute("INSERT OR IGNORE INTO rbac_role_permissions(role_id,permission,effect) VALUES(?,?, 'allow')", (role_id,permission))

    @staticmethod
    def _dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
        return [dict(row) for row in rows]

    @staticmethod
    def _audit(db: sqlite3.Connection, actor: str, action: str, target: str, before: Any, after: Any, source_ip: str = "") -> None:
        db.execute("INSERT INTO rbac_audit(actor,action,target,before_json,after_json,timestamp,source_ip) VALUES(?,?,?,?,?,?,?)", (actor,action,target,json.dumps(before,default=str,sort_keys=True),json.dumps(after,default=str,sort_keys=True),time.time(),source_ip))

    def permissions(self) -> list[dict[str, str]]:
        return [{"id": p, "category": p.split('.',1)[0], "canonical": p} for p in sorted(ALL_PERMISSIONS)] + [{"id": a,"category": a.split('.',1)[0],"canonical": c} for a,c in sorted(PERMISSION_ALIASES.items())]

    def roles(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            roles = self._dicts(db.execute("SELECT * FROM rbac_roles ORDER BY role_type DESC,name"))
            for role in roles:
                role["permissions"] = self._dicts(db.execute("SELECT permission,effect,resource_type,resource_id,scope FROM rbac_role_permissions WHERE role_id=? ORDER BY permission", (role["id"],)))
            return roles

    def role(self, role_id: str) -> dict[str, Any]:
        for role in self.roles():
            if role["id"] == role_id:
                return role
        raise HTTPException(404, "Role not found")

    def create_role(self, payload: dict[str, Any], actor: str, source_ip: str = "") -> dict[str, Any]:
        role_id, now = str(uuid.uuid4()), time.time()
        with self._lock, self._connect() as db:
            try:
                db.execute("INSERT INTO rbac_roles VALUES(?,?,?,?,?,?,?,?,?,?)", (role_id,str(payload["name"]).strip(),str(payload.get("description") or ""),int(payload.get("active",True)),"custom",0,now,actor,now,actor))
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, "Role name already exists") from exc
            self._replace_role_permissions(db, role_id, payload.get("permissions") or [])
            self._audit(db,actor,"role.create",role_id,{},payload,source_ip)
        return self.role(role_id)

    def update_role(self, role_id: str, payload: dict[str, Any], actor: str, source_ip: str = "") -> dict[str, Any]:
        before = self.role(role_id)
        with self._lock, self._connect() as db:
            if before["protected"] and payload.get("name") not in (None,before["name"]):
                raise HTTPException(409,"System role name is protected")
            db.execute("UPDATE rbac_roles SET name=?,description=?,active=?,updated_at=?,updated_by=? WHERE id=?", (payload.get("name",before["name"]),payload.get("description",before["description"]),int(payload.get("active",bool(before["active"]))),time.time(),actor,role_id))
            if "permissions" in payload:
                self._replace_role_permissions(db,role_id,payload["permissions"])
            self._audit(db,actor,"role.update",role_id,before,payload,source_ip)
        return self.role(role_id)

    def _replace_role_permissions(self, db: sqlite3.Connection, role_id: str, permissions: list[dict[str, Any]]) -> None:
        db.execute("DELETE FROM rbac_role_permissions WHERE role_id=?",(role_id,))
        for item in permissions:
            permission = normalize_permission_id(str(item["permission"]))
            db.execute("INSERT INTO rbac_role_permissions VALUES(?,?,?,?,?,?)",(role_id,permission,item.get("effect","allow"),item.get("resource_type","global"),item.get("resource_id","*"),item.get("scope","*")))

    def delete_role(self, role_id: str, actor: str, source_ip: str = "") -> None:
        before = self.role(role_id)
        if before["protected"]:
            raise HTTPException(409,"System role is protected")
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM rbac_roles WHERE id=?",(role_id,))
            self._audit(db,actor,"role.delete",role_id,before,{},source_ip)

    def groups(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            groups = self._dicts(db.execute("SELECT * FROM rbac_groups ORDER BY source,name"))
            for group in groups:
                group["roles"] = [r["role_id"] for r in db.execute("SELECT role_id FROM rbac_group_roles WHERE group_id=?",(group["id"],))]
                group["members"] = self._dicts(db.execute("SELECT provider,identity_id,username FROM rbac_group_members WHERE group_id=? ORDER BY username",(group["id"],)))
            return groups

    def create_group(self, payload: dict[str, Any], actor: str, source_ip: str = "") -> dict[str, Any]:
        group_id, now = str(uuid.uuid4()), time.time()
        source = str(payload.get("source") or "local")
        managed = int(source != "local")
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO rbac_groups VALUES(?,?,?,?,?,?,?,?,?,?)",(group_id,str(payload["name"]).strip(),str(payload.get("description") or ""),int(payload.get("active",True)),source,str(payload.get("external_id") or ""),str(payload.get("distinguished_name") or ""),managed,now,now))
            for role_id in payload.get("role_ids") or []:
                db.execute("INSERT OR IGNORE INTO rbac_group_roles VALUES(?,?)",(group_id,role_id))
            self._audit(db,actor,"group.create",group_id,{},payload,source_ip)
        return next(g for g in self.groups() if g["id"] == group_id)

    def set_group_members(self, group_id: str, members: list[dict[str,str]], actor: str, source_ip: str = "") -> None:
        group = next((g for g in self.groups() if g["id"] == group_id),None)
        if not group:
            raise HTTPException(404,"Group not found")
        if group["managed"]:
            raise HTTPException(409,"LDAP-managed group membership cannot be edited locally")
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM rbac_group_members WHERE group_id=?",(group_id,))
            for item in members:
                db.execute("INSERT INTO rbac_group_members VALUES(?,?,?,?)",(group_id,item.get("provider","pam"),item.get("identity_id") or item["username"],item["username"]))
            self._audit(db,actor,"group.members.update",group_id,group.get("members",[]),members,source_ip)

    def external_groups(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            groups = self._dicts(db.execute("SELECT * FROM rbac_external_groups ORDER BY name"))
            for group in groups:
                group["role_ids"] = [r["role_id"] for r in db.execute("SELECT role_id FROM rbac_external_group_roles WHERE external_group_id=?",(group["id"],))]
                group["parent_ids"] = json.loads(group.pop("parent_ids_json") or "[]")
            return groups

    def upsert_external_group(self, provider_id: str, external_id: str, dn: str, name: str, parent_ids: list[str] | None = None, status: str = "active") -> str:
        group_id = str(uuid.uuid5(uuid.NAMESPACE_URL,f"webnas:{provider_id}:{external_id}"))
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO rbac_external_groups(id,provider_id,external_id,distinguished_name,name,status,parent_ids_json,last_seen_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(provider_id,external_id) DO UPDATE SET distinguished_name=excluded.distinguished_name,name=excluded.name,status=excluded.status,parent_ids_json=excluded.parent_ids_json,last_seen_at=excluded.last_seen_at",(group_id,provider_id,external_id,dn,name,status,json.dumps(parent_ids or []),time.time()))
        return group_id

    def map_external_group_role(self, group_id: str, role_id: str, actor: str, source_ip: str = "") -> None:
        with self._lock, self._connect() as db:
            db.execute("INSERT OR IGNORE INTO rbac_external_group_roles VALUES(?,?)",(group_id,role_id))
            self._audit(db,actor,"ldap.mapping.create",group_id,{}, {"role_id":role_id},source_ip)

    def replace_external_memberships(self, provider_id: str, identity_id: str, username: str, group_ids: set[str], direct_group_ids: set[str] | None = None) -> None:
        direct_group_ids = direct_group_ids or group_ids
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM rbac_external_memberships WHERE provider=? AND identity_id=?",(provider_id,identity_id))
            now = time.time()
            for group_id in group_ids:
                db.execute("INSERT INTO rbac_external_memberships VALUES(?,?,?,?,?,?)",(group_id,provider_id,identity_id,username,int(group_id in direct_group_ids),now))

    def assign_user_role(self, user: SessionUser, role_id: str, actor: str, source_ip: str = "") -> None:
        self.role(role_id)
        identity_id = user.identity_id or user.username
        with self._lock, self._connect() as db:
            db.execute("INSERT OR IGNORE INTO rbac_user_roles VALUES(?,?,?,?,?,?)",(user.auth_provider,identity_id,user.username,role_id,time.time(),actor))
            self._audit(db,actor,"assignment.user-role",f"{user.auth_provider}:{identity_id}",{}, {"role_id":role_id},source_ip)

    def revoke_user_role(self, user: SessionUser, role_id: str, actor: str, source_ip: str = "") -> None:
        identity_id = user.identity_id or user.username
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM rbac_user_roles WHERE provider=? AND identity_id=? AND role_id=?",(user.auth_provider,identity_id,role_id))
            self._audit(db,actor,"assignment.user-role.revoke",f"{user.auth_provider}:{identity_id}", {"role_id":role_id},{},source_ip)

    def policies(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            result = self._dicts(db.execute("SELECT * FROM rbac_policies ORDER BY name"))
            for item in result:
                item["conditions"] = json.loads(item.pop("conditions_json") or "{}")
                item["subjects"] = self._dicts(db.execute("SELECT subject_type,subject_id FROM rbac_policy_subjects WHERE policy_id=?",(item["id"],)))
            return result

    def create_policy(self, payload: dict[str, Any], actor: str, source_ip: str = "") -> dict[str, Any]:
        policy_id, now = str(uuid.uuid4()), time.time()
        permission = normalize_permission_id(str(payload["permission"]))
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO rbac_policies VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(policy_id,str(payload["name"]).strip(),str(payload.get("description") or ""),int(payload.get("active",True)),payload.get("effect","allow"),permission,payload.get("resource_type","global"),payload.get("resource_id","*"),payload.get("scope","*"),json.dumps(payload.get("conditions") or {}),now,actor,now,actor))
            for subject in payload.get("subjects") or []:
                db.execute("INSERT INTO rbac_policy_subjects VALUES(?,?,?)",(policy_id,subject["subject_type"],subject["subject_id"]))
            self._audit(db,actor,"policy.create",policy_id,{},payload,source_ip)
        return next(p for p in self.policies() if p["id"] == policy_id)

    def effective_sources(self, user: SessionUser) -> list[DecisionSource]:
        identity_id = user.identity_id or user.username
        out: list[DecisionSource] = []
        with self._connect() as db:
            queries = [
                ("direct-role", """SELECT rp.*,r.id source_id,r.name source_name,'' reason FROM rbac_user_roles ur JOIN rbac_roles r ON r.id=ur.role_id AND r.active=1 JOIN rbac_role_permissions rp ON rp.role_id=r.id WHERE ur.provider=? AND ur.identity_id=?"""),
                ("local-group", """SELECT rp.*,g.id source_id,(g.name||' -> '||r.name) source_name,'' reason FROM rbac_group_members gm JOIN rbac_groups g ON g.id=gm.group_id AND g.active=1 JOIN rbac_group_roles gr ON gr.group_id=g.id JOIN rbac_roles r ON r.id=gr.role_id AND r.active=1 JOIN rbac_role_permissions rp ON rp.role_id=r.id WHERE gm.provider=? AND gm.identity_id=?"""),
                ("ldap-group", """SELECT rp.*,eg.id source_id,(eg.name||' -> '||r.name) source_name,eg.distinguished_name reason FROM rbac_external_memberships em JOIN rbac_external_groups eg ON eg.id=em.external_group_id AND eg.status='active' JOIN rbac_external_group_roles er ON er.external_group_id=eg.id JOIN rbac_roles r ON r.id=er.role_id AND r.active=1 JOIN rbac_role_permissions rp ON rp.role_id=r.id WHERE em.provider=? AND em.identity_id=?"""),
            ]
            for source_type, query in queries:
                for row in db.execute(query,(user.auth_provider,identity_id)):
                    out.append(DecisionSource(row["effect"],row["permission"],source_type,row["source_id"],row["source_name"],row["resource_type"],row["resource_id"],row["scope"],row["reason"]))
            for policy in db.execute("SELECT * FROM rbac_policies WHERE active=1"):
                subjects = list(db.execute("SELECT subject_type,subject_id FROM rbac_policy_subjects WHERE policy_id=?",(policy["id"],)))
                if self._policy_matches(user,subjects,db,json.loads(policy["conditions_json"] or "{}")):
                    out.append(DecisionSource(policy["effect"],policy["permission"],"policy",policy["id"],policy["name"],policy["resource_type"],policy["resource_id"],policy["scope"],"conditional policy"))
        return out

    @staticmethod
    def _policy_matches(user: SessionUser, subjects: list[sqlite3.Row], db: sqlite3.Connection, conditions: dict[str,Any]) -> bool:
        identity_id = user.identity_id or user.username
        if conditions.get("auth_provider") and conditions["auth_provider"] != user.auth_provider:
            return False
        if not subjects:
            return True
        for subject in subjects:
            if subject["subject_type"] == "user" and subject["subject_id"] in {identity_id,user.username}:
                return True
            if subject["subject_type"] == "provider" and subject["subject_id"] == user.auth_provider:
                return True
            if subject["subject_type"] == "group" and db.execute("SELECT 1 FROM rbac_group_members WHERE group_id=? AND provider=? AND identity_id=?",(subject["subject_id"],user.auth_provider,identity_id)).fetchone():
                return True
            if subject["subject_type"] == "external_group" and db.execute("SELECT 1 FROM rbac_external_memberships WHERE external_group_id=? AND provider=? AND identity_id=?",(subject["subject_id"],user.auth_provider,identity_id)).fetchone():
                return True
        return False

    def audit(self, limit: int = 200) -> list[dict[str,Any]]:
        with self._connect() as db:
            return self._dicts(db.execute("SELECT * FROM rbac_audit ORDER BY timestamp DESC LIMIT ?",(min(max(limit,1),1000),)))


def _resource_matches(source: DecisionSource, resource: Resource) -> bool:
    if source.resource_type not in {"global","*",resource.resource_type}: return False
    if source.resource_id not in {"*",resource.resource_id}: return False
    if source.scope in {"","*"}: return True
    return resource.scope == source.scope or resource.scope.startswith(source.scope.rstrip("/")+"/")


class PermissionService:
    """Authoritative resolver: explicit deny > allow > default deny."""
    def __init__(self, repository: PermissionRepository | None = None, cache_ttl: float = 5.0) -> None:
        self.repository = repository or PermissionRepository()
        self.cache_ttl = max(0.0,cache_ttl)
        self._cache: dict[tuple[str,str,str],tuple[float,list[DecisionSource]]] = {}
        self._lock = threading.RLock()

    def invalidate(self) -> None:
        with self._lock: self._cache.clear()

    def sources(self, user: SessionUser) -> list[DecisionSource]:
        key = (user.auth_provider,user.identity_id or user.username,user.username)
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic(): return list(cached[1])
        sources = self.repository.effective_sources(user)
        with self._lock: self._cache[key] = (time.monotonic()+self.cache_ttl,sources)
        return list(sources)

    def explain(self, user: SessionUser, permission: str, resource: Resource | None = None) -> PermissionDecision:
        expected, target = normalize_permission_id(permission), resource or Resource()
        matches = [s for s in self.sources(user) if s.permission == expected and _resource_matches(s,target)]
        denies, allows = [s for s in matches if s.effect=="deny"],[s for s in matches if s.effect=="allow"]
        if denies: return PermissionDecision(False,expected,target,denies+allows,"explicit deny overrides allow")
        if allows: return PermissionDecision(True,expected,target,allows,"permission granted by effective assignment")
        return PermissionDecision(False,expected,target,[],"default deny: no effective grant")

    def can(self,user: SessionUser,permission: str,resource: Resource | None=None)->bool: return self.explain(user,permission,resource).allowed
    def authorize(self,user: SessionUser,permission: str,resource: Resource | None=None)->None:
        decision=self.explain(user,permission,resource)
        if not decision.allowed: raise HTTPException(403,detail={"code":"PERMISSION_REQUIRED",**decision.as_dict()})
    def effective(self,user: SessionUser)->dict[str,Any]:
        permissions=sorted({s.permission for s in self.sources(user)})
        decisions=[self.explain(user,p).as_dict() for p in permissions]
        return {"user":{"username":user.username,"provider":user.auth_provider,"identity_id":user.identity_id or user.username},"permissions":decisions,"allowed":[d["permission"] for d in decisions if d["result"]=="ALLOW"],"denied":[d["permission"] for d in decisions if d["result"]=="DENY"]}


_service: PermissionService | None = None
_service_lock = threading.Lock()
def permission_service() -> PermissionService:
    global _service
    with _service_lock:
        if _service is None: _service = PermissionService()
        return _service
