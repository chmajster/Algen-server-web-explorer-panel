from __future__ import annotations

PACKAGE_MANAGER_ALIASES = {
    "apt": "apt-get",
    "apt-get": "apt-get",
    "dnf": "dnf",
    "dnf5": "dnf",
    "yum": "yum",
    "yum4": "yum",
    "zypper": "zypper",
    "pacman": "pacman",
    "apk": "apk",
}

PACKAGE_MANAGER_EXECUTABLES = {
    "apt-get": "apt-get",
    "dnf": "dnf",
    "yum": "yum",
    "zypper": "zypper",
    "pacman": "pacman",
    "apk": "apk",
}

PACKAGE_MANAGER_CANDIDATES = {
    "apt-get": ("apt-get", "apt"),
    "dnf": ("dnf", "dnf5"),
    "yum": ("yum", "yum4"),
    "zypper": ("zypper",),
    "pacman": ("pacman",),
    "apk": ("apk",),
}


def normalize_package_manager(value: str | None) -> str | None:
    """Return the canonical name used by manifests, plans and the UI."""

    if value is None:
        return None
    normalized = value.strip().lower()
    return PACKAGE_MANAGER_ALIASES.get(normalized, normalized) or None


def package_manager_executable(value: str | None) -> str | None:
    normalized = normalize_package_manager(value)
    return PACKAGE_MANAGER_EXECUTABLES.get(normalized) if normalized else None


def find_package_manager(canonical_names: tuple[str, ...], lookup) -> str | None:
    for canonical in canonical_names:
        for executable in PACKAGE_MANAGER_CANDIDATES[canonical]:
            if lookup(executable):
                return canonical
    return None


def resolve_package_manager_executable(value: str | None, lookup) -> str | None:
    normalized = normalize_package_manager(value)
    if normalized is None:
        return None
    for executable in PACKAGE_MANAGER_CANDIDATES[normalized]:
        if lookup(executable):
            return executable
    return PACKAGE_MANAGER_EXECUTABLES[normalized]
