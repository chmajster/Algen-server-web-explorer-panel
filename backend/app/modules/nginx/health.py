import shutil

if not shutil.which("nginx"):
    raise SystemExit("nginx is unavailable after installation")
print("nginx executable is available")
