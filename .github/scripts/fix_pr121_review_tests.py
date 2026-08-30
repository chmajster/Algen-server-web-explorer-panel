from pathlib import Path


path = Path("backend/tests/test_security_center.py")
text = path.read_text(encoding="utf-8")
text = text.replace("import app.modules.security_center.service as security_service_module\n\n", "")
if "import importlib\n" not in text:
    text = text.replace("from pathlib import Path\n", "from pathlib import Path\n\nimport importlib\n", 1)
anchor = "from app.modules.security_center.service import SecurityCenterService\n"
if "security_service_module = importlib.import_module" not in text:
    if anchor not in text:
        raise SystemExit("security import anchor missing")
    text = text.replace(anchor, anchor + "\nsecurity_service_module = importlib.import_module(\"app.modules.security_center.service\")\n", 1)
path.write_text(text, encoding="utf-8")

path = Path("backend/tests/test_network_tools.py")
text = path.read_text(encoding="utf-8")
old = '''    monkeypatch.setattr("app.modules.network_tools.service.shutil.which", lambda _name: "/usr/bin/dig")
    def fake_run(args, **_kwargs):
        observed.extend(args)
        return Result()
    monkeypatch.setattr("app.modules.network_tools.service.subprocess.run", fake_run)
'''
new = '''    import importlib
    network_service_module = importlib.import_module("app.modules.network_tools.service")
    monkeypatch.setattr(network_service_module.shutil, "which", lambda _name: "/usr/bin/dig")
    def fake_run(args, **_kwargs):
        observed.extend(args)
        return Result()
    monkeypatch.setattr(network_service_module.subprocess, "run", fake_run)
'''
if old in text:
    text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
