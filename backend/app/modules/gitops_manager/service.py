from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from ...config import get_config
from ...jobs.models import JobPriority
from ...jobs.service import JobContext, service as jobs

_SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("authorization", re.compile(r"(?i)\b(?:authorization|bearer)\b\s*[:=]\s*\S+")),
    ("api-token", re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*[^\s#]{8,}")),
    ("password", re.compile(r"(?i)\b(?:password|passwd|secret)\b\s*[:=]\s*[^\s#]{4,}")),
    ("github-token", re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b")),
]
_SAFE_EXPORTS = {"webnas/config.yaml", "webnas/modules.json"}
_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")


class GitOpsUnavailable(RuntimeError):
    pass


class GitOpsConflict(RuntimeError):
    pass


class GitOpsService:
    def __init__(self) -> None:
        self.root = Path(get_config().paths.data_dir) / "gitops-config"
        self.settings_path = Path(get_config().paths.data_dir) / "gitops-settings.json"

    def _git_binary(self) -> str:
        binary = shutil.which("git")
        if not binary:
            raise GitOpsUnavailable("git is not installed")
        return binary

    def _run(self, args: list[str], *, timeout: int = 60, check: bool = False) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(args, cwd=self.root, capture_output=True, text=True, timeout=timeout, check=False, shell=False,
            env={**__import__("os").environ, "GIT_TERMINAL_PROMPT": "0"})
        if check and result.returncode != 0:
            message = (result.stderr or result.stdout or "Git command failed")[:2000]
            if "CONFLICT" in message.upper() or "MERGE_HEAD" in message:
                raise GitOpsConflict(message)
            raise RuntimeError(message)
        return result

    @staticmethod
    def _valid_ref(ref: str) -> str:
        value = ref.strip()
        if not _REF_RE.fullmatch(value) or value.startswith("-") or ".." in value or "//" in value:
            raise ValueError("invalid Git reference")
        return value

    @staticmethod
    def _safe_path(path: str) -> str:
        normalized = str(PurePosixPath(path))
        if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized or normalized not in _SAFE_EXPORTS:
            raise ValueError("path is not in the GitOps allowlist")
        return normalized

    def settings(self) -> dict[str, str]:
        if not self.settings_path.exists():
            return {"remote": "", "branch": "main"}
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"remote": "", "branch": "main"}
        return {"remote": str(data.get("remote") or ""), "branch": str(data.get("branch") or "main")}

    def configure(self, remote: str, branch: str) -> dict[str, Any]:
        self._valid_ref(branch)
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps({"remote": remote, "branch": branch}, indent=2), encoding="utf-8")
        self.settings_path.chmod(0o600)
        self.init_repository()
        git = self._git_binary()
        existing = self._run([git, "remote", "get-url", "origin"], timeout=10)
        if remote:
            command = [git, "remote", "set-url", "origin", remote] if existing.returncode == 0 else [git, "remote", "add", "origin", remote]
            self._run(command, timeout=15, check=True)
        elif existing.returncode == 0:
            self._run([git, "remote", "remove", "origin"], timeout=15, check=True)
        return self.overview()

    def init_repository(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        git = self._git_binary()
        if not (self.root / ".git").exists():
            self._run([git, "init"], timeout=20, check=True)
            self._run([git, "config", "user.name", "WebNAS GitOps"], timeout=10, check=True)
            self._run([git, "config", "user.email", "webnas@localhost"], timeout=10, check=True)
            ignore = ".env\n*.key\n*.pem\ncredentials*\nsecrets*\n"
            (self.root / ".gitignore").write_text(ignore, encoding="utf-8")

    def export_configuration(self) -> list[str]:
        self.init_repository()
        cfg = get_config().model_dump(mode="json")
        security = dict(cfg.get("security") or {})
        security.pop("session_secret", None)
        cfg["security"] = security
        webnas = self.root / "webnas"
        webnas.mkdir(parents=True, exist_ok=True)
        (webnas / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=True), encoding="utf-8")
        # Keep module export deliberately metadata-only; module credentials/state remain outside GitOps.
        (webnas / "modules.json").write_text(json.dumps({"generated_at": int(time.time()), "note": "Module credentials and Secrets Manager data are excluded."}, indent=2), encoding="utf-8")
        return sorted(_SAFE_EXPORTS)

    def scan_secrets(self) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for relative in sorted(_SAFE_EXPORTS):
            path = self.root / relative
            if not path.exists():
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for kind, pattern in _SECRET_PATTERNS:
                    if pattern.search(line):
                        findings.append({"path": relative, "line": number, "type": kind, "value": "[REDACTED]"})
        return findings

    def _ensure_clean_secret_scan(self) -> None:
        findings = self.scan_secrets()
        if findings:
            first = findings[0]
            raise ValueError(f"Commit blocked: possible {first['type']} in {first['path']}:{first['line']}")

    def overview(self) -> dict[str, Any]:
        self.init_repository()
        git = self._git_binary()
        settings = self.settings()
        branch = self._run([git, "branch", "--show-current"], timeout=10).stdout.strip() or settings["branch"]
        head = self._run([git, "rev-parse", "--short=12", "HEAD"], timeout=10)
        status = self._run([git, "status", "--porcelain=v1"], timeout=10)
        ahead = behind = 0
        upstream = self._run([git, "rev-list", "--left-right", "--count", "HEAD...@{upstream}"], timeout=10)
        if upstream.returncode == 0:
            parts = upstream.stdout.split()
            if len(parts) == 2:
                ahead, behind = int(parts[0]), int(parts[1])
        return {"repository": str(self.root), "remote": settings["remote"], "branch": branch, "head": head.stdout.strip() if head.returncode == 0 else "", "working_tree_clean": not bool(status.stdout.strip()), "local_changes": len(status.stdout.splitlines()), "ahead": ahead, "behind": behind}

    def changes(self) -> list[dict[str, str]]:
        self.init_repository(); git = self._git_binary()
        result = self._run([git, "status", "--porcelain=v1"], timeout=10)
        items = []
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            code, path = line[:2], line[3:]
            kind = "untracked" if code == "??" else "added" if "A" in code else "deleted" if "D" in code else "renamed" if "R" in code else "modified"
            items.append({"status": code, "kind": kind, "path": path})
        return items

    def diff(self, ref: str = "") -> str:
        self.init_repository(); git = self._git_binary()
        args = [git, "diff", "--no-ext-diff", "--unified=3"]
        if ref:
            args.append(self._valid_ref(ref))
        return self._run(args, timeout=20).stdout[:200_000]

    def history(self, limit: int = 100) -> list[dict[str, str]]:
        self.init_repository(); git = self._git_binary()
        fmt = "%H%x1f%an%x1f%aI%x1f%s"
        result = self._run([git, "log", f"--max-count={min(max(limit,1),500)}", f"--pretty=format:{fmt}"], timeout=20)
        if result.returncode != 0:
            return []
        items = []
        for line in result.stdout.splitlines():
            parts = line.split("\x1f", 3)
            if len(parts) == 4:
                items.append({"sha": parts[0], "author": parts[1], "date": parts[2], "message": parts[3]})
        return items

    def commit(self, message: str) -> dict[str, Any]:
        self.export_configuration(); self._ensure_clean_secret_scan(); git = self._git_binary()
        self._run([git, "add", "--", ".gitignore", *_SAFE_EXPORTS], timeout=20, check=True)
        staged = self._run([git, "diff", "--cached", "--quiet"], timeout=10)
        if staged.returncode == 0:
            return {"committed": False, "reason": "no changes"}
        self._run([git, "commit", "-m", message], timeout=30, check=True)
        return {"committed": True, "head": self.overview()["head"]}

    def fetch(self, context: JobContext | None = None) -> dict[str, Any]:
        self.init_repository(); git = self._git_binary(); settings = self.settings()
        if not settings["remote"]:
            raise GitOpsUnavailable("Git remote is not configured")
        if context: context.set_progress(20, "Fetching remote", current_step="fetch")
        self._run([git, "fetch", "--prune", "origin"], timeout=120, check=True)
        if context: context.set_progress(100, "Remote fetched", current_step="verify")
        return self.overview()

    def pull(self, context: JobContext | None = None) -> dict[str, Any]:
        self.init_repository(); git = self._git_binary(); settings = self.settings(); branch = self._valid_ref(settings["branch"])
        if not settings["remote"]: raise GitOpsUnavailable("Git remote is not configured")
        self._ensure_clean_secret_scan()
        if context: context.set_progress(15, "Fetching remote", current_step="fetch")
        self._run([git, "fetch", "--prune", "origin"], timeout=120, check=True)
        if context: context.set_progress(60, "Fast-forwarding branch", current_step="merge")
        self._run([git, "merge", "--ff-only", f"origin/{branch}"], timeout=60, check=True)
        if context: context.set_progress(100, "Pull complete", current_step="verify")
        return self.overview()

    def push(self, context: JobContext | None = None) -> dict[str, Any]:
        self.init_repository(); git = self._git_binary(); settings = self.settings(); branch = self._valid_ref(settings["branch"])
        if not settings["remote"]: raise GitOpsUnavailable("Git remote is not configured")
        self._ensure_clean_secret_scan()
        if context: context.set_progress(20, "Pushing branch", current_step="push")
        self._run([git, "push", "origin", f"HEAD:{branch}"], timeout=120, check=True)
        if context: context.set_progress(100, "Push complete", current_step="verify")
        return self.overview()

    def checkout_branch(self, branch: str) -> dict[str, Any]:
        branch = self._valid_ref(branch); self.init_repository(); git = self._git_binary()
        existing = self._run([git, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], timeout=10)
        self._run([git, "checkout", branch] if existing.returncode == 0 else [git, "checkout", "-b", branch], timeout=30, check=True)
        current = self.settings(); self.configure(current["remote"], branch)
        return self.overview()

    def restore_file(self, path: str, ref: str) -> dict[str, Any]:
        relative = self._safe_path(path); ref = self._valid_ref(ref); self.init_repository(); git = self._git_binary()
        self._run([git, "restore", "--source", ref, "--", relative], timeout=30, check=True)
        self._ensure_clean_secret_scan()
        return {"path": relative, "ref": ref, "restored": True}

    def revert(self, ref: str) -> dict[str, Any]:
        ref = self._valid_ref(ref); self.init_repository(); git = self._git_binary()
        self._run([git, "revert", "--no-edit", ref], timeout=60, check=True)
        self._ensure_clean_secret_scan()
        return self.overview()

    def enqueue(self, action: str, actor: str):
        handlers = {"fetch": self.fetch, "pull": self.pull, "push": self.push}
        if action not in handlers: raise ValueError("unsupported GitOps job action")
        return jobs().submit_callable(job_type=f"gitops.{action}", module="gitops-config-manager", created_by=actor,
            handler=lambda context, _metadata: handlers[action](context), retryable=action in {"fetch", "push"}, cancellable=False,
            priority=JobPriority.normal, max_retries=1, timeout=180, name=f"GitOps {action}", dedup_key=f"gitops.{action}")


_instance: GitOpsService | None = None


def service() -> GitOpsService:
    global _instance
    if _instance is None: _instance = GitOpsService()
    return _instance
