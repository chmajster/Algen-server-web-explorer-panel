from pathlib import Path
import subprocess

BASE_SHA = "244613630b59ae496962ac4c88014a36bc29258b"
PATH = "frontend/src/features/modules/hosts/HostsManagerApp.tsx"

current = Path(PATH).read_text()
current_start = current.index("function Credentials({")
current_end = current.index("\nfunction Repositories", current_start)
credentials = current[current_start:current_end]

base = subprocess.check_output(["git", "show", f"{BASE_SHA}:{PATH}"], text=True)
base_start = base.index("function Credentials({")
base_end = base.index("\nfunction Repositories", base_start)

Path(PATH).write_text(base[:base_start] + credentials + base[base_end:])
