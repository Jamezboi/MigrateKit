from pathlib import Path

p = Path('migratekit_pro.py')
s = p.read_text(encoding='utf-8')

s = s.replace('VERSION = "1.2.0"', 'VERSION = "1.2.2"', 1)

marker = 'class Engine:\n'
helper = '''from github_upload import upload_archive\n\n\n'''
if 'from github_upload import upload_archive' not in s:
    if marker not in s:
        raise SystemExit('Engine marker not found')
    s = s.replace(marker, helper + marker, 1)

old_call = '        self.put("DONE", {"path": str(out), "size": size, "files": state["files"], "skipped": state["skipped"], "ratio": size / max(1, state["done"]), "elapsed": elapsed}, True)'
new_call = '''        github_url = None\n        try:\n            github_url = upload_archive(out, self.log, lambda msg: self.put("STATUS", msg, True))\n        except Exception as exc:\n            self.log(f"GitHub upload failed: {exc}")\n        self.put("DONE", {"path": str(out), "size": size, "files": state["files"], "skipped": state["skipped"], "ratio": size / max(1, state["done"]), "elapsed": elapsed, "github_url": github_url}, True)'''
if old_call not in s:
    raise SystemExit('Backup completion marker not found')
s = s.replace(old_call, new_call, 1)

# Consume the optional height override so callers may specify height without duplicate kwargs.
old_btn = 'return ctk.CTkButton(p, text=text, command=command, fg_color=kw.pop("fg", BLUE), hover_color=kw.pop("hover", BLUE_H), corner_radius=9, height=42, font=ctk.CTkFont(size=13, weight="bold"), **kw)'
new_btn = 'height=kw.pop("height", 42); return ctk.CTkButton(p, text=text, command=command, fg_color=kw.pop("fg", BLUE), hover_color=kw.pop("hover", BLUE_H), corner_radius=9, height=height, font=ctk.CTkFont(size=13, weight="bold"), **kw)'
if old_btn in s:
    s = s.replace(old_btn, new_btn, 1)

p.write_text(s, encoding='utf-8')
print('GitHub backup uploader patch applied.')
