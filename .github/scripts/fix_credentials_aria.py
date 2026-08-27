from pathlib import Path

path = Path("frontend/src/features/modules/hosts/HostsManagerApp.tsx")
text = path.read_text()
replacements = [
    ('<select autoFocus value={type}', '<select aria-label={t("hosts.credentials.type")} autoFocus value={type}'),
    ('<input required={profile.username.required} value={username}', '<input aria-label={profile.username.label} required={profile.username.required} value={username}'),
    ('<textarea rows={7} required={!editing && profile.secret.required}', '<textarea aria-label={profile.secret.label} rows={7} required={!editing && profile.secret.required}'),
    ('<input type="password" required={!editing && profile.secret.required}', '<input aria-label={profile.secret.label} type="password" required={!editing && profile.secret.required}'),
    ('<input type="password" value={passphrase}', '<input aria-label={t("hosts.credentials.passphrase")} type="password" value={passphrase}'),
]
for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one occurrence of {old!r}, got {count}")
    text = text.replace(old, new, 1)
path.write_text(text)
