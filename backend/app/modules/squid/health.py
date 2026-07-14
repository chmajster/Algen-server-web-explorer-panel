import shutil

if not shutil.which("squid"):
    raise SystemExit("squid is unavailable after installation")
print("squid executable is available")
