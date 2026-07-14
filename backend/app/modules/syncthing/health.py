import shutil

if not shutil.which("syncthing"):
    raise SystemExit("syncthing is unavailable after installation")
print("syncthing executable is available")
