from pathlib import Path
import json
import subprocess

BASE_SHA = "244613630b59ae496962ac4c88014a36bc29258b"

translations = {
    "frontend/src/locales/pl-PL.json": {
        "replace": ('"hosts.credentials.add": "Dodaj poświadczenie SSH"', '"hosts.credentials.add": "Dodaj poświadczenie"'),
        "add": {
            "common.description": "Opis",
            "hosts.credentials.account": "Konto / użytkownik",
            "hosts.credentials.typeHint": "Najpierw wybierz typ poświadczenia. Formularz pokaże tylko pola wymagane dla tego typu.",
            "hosts.credentials.typeLocked": "Typ istniejącego poświadczenia jest zablokowany. Utwórz nowe poświadczenie, aby użyć innego typu.",
            "hosts.credentials.namePlaceholder": "np. Proxmox Lab, SSH root, Git deploy key",
            "hosts.credentials.field.login": "Login / nazwa użytkownika",
            "hosts.credentials.field.password": "Hasło",
            "hosts.credentials.field.sshUser": "Użytkownik SSH",
            "hosts.credentials.field.sshPassword": "Hasło SSH",
            "hosts.credentials.field.privateKey": "Klucz prywatny",
            "hosts.credentials.field.becomePassword": "Hasło sudo / root",
            "hosts.credentials.field.apiToken": "Token API",
            "hosts.credentials.field.genericSecret": "Sekret",
            "hosts.credentials.field.proxmoxTokenId": "ID tokenu Proxmox",
            "hosts.credentials.field.proxmoxTokenIdHint": "Format: user@realm!tokenid, np. automation@pve!algen.",
            "hosts.credentials.field.proxmoxTokenSecret": "Sekret tokenu Proxmox",
            "hosts.credentials.field.redfishUser": "Login Redfish",
            "hosts.credentials.field.redfishPassword": "Hasło Redfish",
            "hosts.credentials.field.ipmiUser": "Login IPMI",
            "hosts.credentials.field.ipmiPassword": "Hasło IPMI",
            "hosts.credentials.field.gitUser": "Użytkownik Git",
            "hosts.credentials.field.optional": "Pole opcjonalne.",
            "hosts.credentials.wolNoSecret": "Wake-on-LAN nie wymaga sekretu.",
            "hosts.credentials.wolNoSecretHint": "Adres MAC i parametry WOL są konfigurowane w profilu zasilania hosta.",
        },
    },
    "frontend/src/locales/en-US.json": {
        "replace": ('"hosts.credentials.add": "Add SSH credential"', '"hosts.credentials.add": "Add credential"'),
        "add": {
            "common.description": "Description",
            "hosts.credentials.account": "Account / username",
            "hosts.credentials.typeHint": "Choose the credential type first. The form will show only fields required for that type.",
            "hosts.credentials.typeLocked": "The type of an existing credential is locked. Create a new credential to use another type.",
            "hosts.credentials.namePlaceholder": "e.g. Proxmox Lab, SSH root, Git deploy key",
            "hosts.credentials.field.login": "Login / username",
            "hosts.credentials.field.password": "Password",
            "hosts.credentials.field.sshUser": "SSH user",
            "hosts.credentials.field.sshPassword": "SSH password",
            "hosts.credentials.field.privateKey": "Private key",
            "hosts.credentials.field.becomePassword": "sudo / root password",
            "hosts.credentials.field.apiToken": "API token",
            "hosts.credentials.field.genericSecret": "Secret",
            "hosts.credentials.field.proxmoxTokenId": "Proxmox token ID",
            "hosts.credentials.field.proxmoxTokenIdHint": "Format: user@realm!tokenid, for example automation@pve!algen.",
            "hosts.credentials.field.proxmoxTokenSecret": "Proxmox token secret",
            "hosts.credentials.field.redfishUser": "Redfish login",
            "hosts.credentials.field.redfishPassword": "Redfish password",
            "hosts.credentials.field.ipmiUser": "IPMI login",
            "hosts.credentials.field.ipmiPassword": "IPMI password",
            "hosts.credentials.field.gitUser": "Git username",
            "hosts.credentials.field.optional": "Optional field.",
            "hosts.credentials.wolNoSecret": "Wake-on-LAN does not require a secret.",
            "hosts.credentials.wolNoSecretHint": "The MAC address and WOL parameters are configured in the host power profile.",
        },
    },
}

for path, spec in translations.items():
    raw = subprocess.check_output(["git", "show", f"{BASE_SHA}:{path}"], text=True)
    old, new = spec["replace"]
    if old not in raw:
        raise SystemExit(f"missing translation marker in {path}: {old}")
    raw = raw.replace(old, new, 1)
    stripped = raw.rstrip()
    if not stripped.endswith("}"):
        raise SystemExit(f"invalid locale document: {path}")
    body = stripped[:-1].rstrip()
    additions = spec["add"]
    lines = [f"  {json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)}" for key, value in additions.items()]
    Path(path).write_text(body + ",\n" + ",\n".join(lines) + "\n}\n")
