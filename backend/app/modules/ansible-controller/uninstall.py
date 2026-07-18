"""Package removal deliberately preserves controller data and remote accounts."""

from pathlib import Path

root = Path("/var/lib/webnas/ansible-controller")
for child in (root / "tmp", root / "runs"):
    if child.is_dir():
        for item in child.iterdir():
            if item.is_file() and not item.is_symlink():
                item.unlink(missing_ok=True)
print("Controller data, credentials, keys and remote algen-ansible accounts were preserved")
