from pathlib import Path

path = Path('frontend/src/features/modules/hosts/HostsManagerApp.test.tsx')
text = path.read_text()
old = 'import { fireEvent, render, screen, waitFor } from "@testing-library/react";'
new = 'import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";'
if old not in text:
    raise SystemExit('testing-library import marker not found')
text = text.replace(old, new, 1)
old = '    const moduleSelect = await screen.findByRole("button", { name: "hosts.credentials.sharedWith" });\n'
new = '    const credentialDialog = screen.getByRole("dialog");\n    const moduleSelect = await within(credentialDialog).findByRole("button", { name: "hosts.credentials.sharedWith" });\n'
if old not in text:
    raise SystemExit('module selector test marker not found')
text = text.replace(old, new, 1)
path.write_text(text)
