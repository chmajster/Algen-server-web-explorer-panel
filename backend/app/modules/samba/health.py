import shutil

if not shutil.which("smbd"):
    raise SystemExit("smbd is unavailable after installation")
print("smbd executable is available")
