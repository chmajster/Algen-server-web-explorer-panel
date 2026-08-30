from pathlib import Path

path = Path("backend/app/modules/firewall_manager/service.py")
text = path.read_text(encoding="utf-8")
old = '''        except Exception:
            for item in current:
                if backend == FirewallBackend.nftables and not item.editable:
                    continue
                try:
                    self.add_rule(self._input_from_rule(item))
                except Exception:
                    pass
            raise
'''
new = '''        except Exception as error:
            rollback_failed = False
            for item in current:
                if backend == FirewallBackend.nftables and not item.editable:
                    continue
                try:
                    self.add_rule(self._input_from_rule(item))
                except Exception:
                    rollback_failed = True
            if rollback_failed:
                raise FirewallError("firewall backup restore failed and rollback could not be completed") from error
            raise
'''
if old not in text:
    raise SystemExit("rollback anchor missing")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
