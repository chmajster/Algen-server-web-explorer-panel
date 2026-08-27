from pathlib import Path
import subprocess

BASE_SHA = "244613630b59ae496962ac4c88014a36bc29258b"
PATH = "frontend/src/features/modules/hosts/HostsManagerApp.tsx"
app = Path(PATH)
current = app.read_text()
current_start = current.index("function Credentials({")
current_end = current.index("\nfunction SettingsWorkspace", current_start)
dynamic_credentials = current[current_start:current_end]

original = subprocess.check_output(["git", "show", f"{BASE_SHA}:{PATH}"], text=True)
original_start = original.index("function Credentials({")
original_end = original.index("\nfunction Repositories", original_start)
app.write_text(original[:original_start] + dynamic_credentials + original[original_end:])
