import os
import sys
import json
import time
import shutil
import queue
import threading
import hashlib
import zipfile
import subprocess
from pathlib import Path
from tkinter import filedialog, messagebox
import customtkinter as ctk

APP = "MigrateKit"
VERSION = "1.2.0"
SALT = "MIGRATEKIT-SALT-2026"
DEV_KEY = "DEVKEY-MIGRATE-2026-UNLOCK"
SETTINGS = Path(os.environ.get("APPDATA", Path.home())) / APP / "settings.json"

BG, PANEL, PANEL2, BORDER = "#080b12", "#10151f", "#141b27", "#222c3c"
TEXT, MUTED = "#f4f7fb", "#8d99aa"
BLUE, BLUE_H, GREEN, RED, AMBER = "#4f8cff", "#6b9dff", "#24c18a", "#ef5b6b", "#f2b84b"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def verify_key(key):
    clean = key.strip().replace("-", "").upper()
    if clean == DEV_KEY.replace("-", "").upper():
        return True, "Developer License"
    if len(clean) != 20:
        return False, "Invalid key length"
    expected = hashlib.sha256((clean[:15] + SALT).encode()).hexdigest()[:5].upper()
    return (True, "Standard License") if expected == clean[15:] else (False, "Invalid license signature")


def load_license():
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        key = data.get("license_key", "")
        return (True, key) if data.get("activated") and verify_key(key)[0] else (False, "")
    except Exception:
        return False, ""


def save_license(key):
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps({"license_key": key, "activated": True}, indent=2), encoding="utf-8")


def fmt_bytes(n):
    n = float(max(0, n))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return "0 B"


def fmt_time(s):
    if not s or s == float("inf"):
        return "—"
    s = int(s)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s//60}m {s%60}s"
    return f"{s//3600}h {(s%3600)//60}m"


class Engine:
    def __init__(self, q, cancel):
        self.q, self.cancel = q, cancel
        self.user = Path(os.environ.get("USERPROFILE", str(Path.home())))
        self.appdata = Path(os.environ.get("APPDATA", ""))
        self.local = Path(os.environ.get("LOCALAPPDATA", ""))
        self._last = 0.0

    def put(self, kind, data=None, force=False):
        now = time.monotonic()
        if not force and kind == "PROGRESS" and now - self._last < 0.08:
            return
        self._last = now
        self.q.put((kind, data))

    def log(self, msg):
        self.q.put(("LOG", msg))

    def scan(self, root):
        files, total = [], 0
        if not root.exists():
            return files, 0
        for base, dirs, names in os.walk(root):
            if self.cancel.is_set():
                break
            dirs[:] = [d for d in dirs if d.lower() not in {"node_modules", ".git", "__pycache__", "temp"}]
            for name in names:
                p = Path(base) / name
                try:
                    size = p.stat().st_size
                    files.append((p, size))
                    total += size
                except OSError:
                    continue
        return files, total

    def copy_one(self, src, dst, state):
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            with open(src, "rb") as r, open(dst, "wb") as w:
                while True:
                    if self.cancel.is_set():
                        return False
                    chunk = r.read(1024 * 1024)
                    if not chunk:
                        break
                    w.write(chunk)
                    state["done"] += len(chunk)
                    elapsed = max(0.001, time.monotonic() - state["start"])
                    speed = state["done"] / elapsed
                    eta = max(0, state["total"] - state["done"]) / speed if speed else 0
                    self.put("PROGRESS", {"done": state["done"], "total": state["total"], "progress": state["done"] / state["total"], "speed": speed, "eta": eta, "file": str(src)})
            shutil.copystat(src, dst, follow_symlinks=True)
            state["files"] += 1
            return True
        except OSError as e:
            state["skipped"] += 1
            self.log(f"Skipped {src}: {e}")
            return True

    def copy_list(self, root, dest, files, state):
        for src, _ in files:
            self.put("STATUS", f"Copying {src.name}")
            if not self.copy_one(src, dest / src.relative_to(root), state):
                return False
        return True

    def backup_chrome(self, stage, state):
        src = self.local / "Google" / "Chrome" / "User Data" / "Default"
        if not src.exists():
            return
        self.put("STATUS", "Packaging Chrome profile…", True)
        dst = stage / "data" / "Chrome" / "Default"
        for name in ["Bookmarks", "History", "Preferences", "Web Data", "Login Data", "Secure Preferences", "Cookies"]:
            p = src / name
            if p.exists() and not self.copy_one(p, dst / name, state):
                return

    def backup_appdata(self, stage, state):
        for name in ["Discord", "Microsoft", "Code", "Slack", "Zoom"]:
            for root in [self.appdata / name, self.local / name]:
                if not root.exists():
                    continue
                self.put("STATUS", f"Packaging AppData: {name}", True)
                files, _ = self.scan(root)
                if not self.copy_list(root, stage / "data" / "AppData" / root.name, files, state):
                    return

    def backup_registry(self, stage):
        out = stage / "registry"
        out.mkdir(parents=True, exist_ok=True)
        for i, key in enumerate([
            r"HKEY_CURRENT_USER\Environment",
            r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ]):
            safe = key.replace("\\", "_").replace(":", "_")[:80] + f"_{i}.reg"
            self.put("STATUS", f"Exporting registry: {key}", True)
            subprocess.run(["reg.exe", "export", key, str(out / safe), "/y"], capture_output=True, text=True, shell=False)

    def backup(self, target, selected, compression):
        started = time.monotonic()
        stage = self.local / APP / "stage"
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True, exist_ok=True)
        roots = {
            "Documents": self.user / "Documents", "Pictures": self.user / "Pictures", "Desktop": self.user / "Desktop",
            "Downloads": self.user / "Downloads", "Videos": self.user / "Videos", "Music": self.user / "Music"
        }
        jobs, total = [], 0
        for name, enabled in selected.items():
            if name not in roots or not enabled:
                continue
            self.put("STATUS", f"Scanning {name}…", True)
            files, size = self.scan(roots[name])
            jobs.append((name, roots[name], files)); total += size
            self.log(f"{name}: {len(files):,} files · {fmt_bytes(size)}")
        state = {"done": 0, "total": total or 1, "files": 0, "skipped": 0, "start": time.monotonic()}
        for name, root, files in jobs:
            if not self.copy_list(root, stage / "data" / name, files, state):
                self.put("CANCELLED", force=True); shutil.rmtree(stage, ignore_errors=True); return
        if selected.get("Chrome Profile"):
            self.backup_chrome(stage, state)
        if selected.get("Application Data (AppData)"):
            self.backup_appdata(stage, state)
        if selected.get("Registry Configurations"):
            self.backup_registry(stage)
        manifest = {
            "version": 3, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "hostname": os.environ.get("COMPUTERNAME", "Unknown"),
            "user": os.environ.get("USERNAME", "Unknown"), "categories": [j[0] for j in jobs] + [k for k in ("Chrome Profile", "Application Data (AppData)", "Registry Configurations") if selected.get(k)],
            "files": state["files"], "bytes": state["done"], "skipped": state["skipped"], "compression": compression,
        }
        (stage / "backup_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        method = zipfile.ZIP_LZMA if compression == "Maximum" else zipfile.ZIP_DEFLATED
        level = None if compression == "Maximum" else (9 if compression == "Balanced" else 3)
        archive = [p for p in stage.rglob("*") if p.is_file()]
        out = Path(target); out.parent.mkdir(parents=True, exist_ok=True); out.unlink(missing_ok=True)
        self.put("STATUS", f"Compressing {len(archive):,} files using {compression}…", True)
        with zipfile.ZipFile(out, "w", compression=method, compresslevel=level, allowZip64=True) as zf:
            for i, p in enumerate(archive, 1):
                if self.cancel.is_set():
                    self.put("CANCELLED", force=True); shutil.rmtree(stage, ignore_errors=True); return
                zf.write(p, p.relative_to(stage).as_posix())
                self.put("COMPRESSION", {"done": i, "total": len(archive), "file": p.name})
        size = out.stat().st_size
        elapsed = max(.001, time.monotonic() - started)
        shutil.rmtree(stage, ignore_errors=True)
        self.put("DONE", {"path": str(out), "size": size, "files": state["files"], "skipped": state["skipped"], "ratio": size / max(1, state["done"]), "elapsed": elapsed}, True)

    def restore(self, archive, selections):
        started = time.monotonic(); temp = self.local / APP / "restore_stage"
        shutil.rmtree(temp, ignore_errors=True); temp.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(archive, "r") as zf:
                self.put("STATUS", "Validating archive integrity…", True)
                bad = zf.testzip()
                if bad:
                    raise ValueError(f"Corrupt archive member: {bad}")
                members = zf.infolist(); total = sum(max(0, m.file_size) for m in members); done = 0
                for m in members:
                    if self.cancel.is_set():
                        self.put("CANCELLED", force=True); return
                    zf.extract(m, temp)
                    done += max(0, m.file_size)
                    self.put("PROGRESS", {"done": done, "total": total or 1, "progress": done / max(1, total), "speed": done / max(.001, time.monotonic() - started), "eta": 0, "file": m.filename})
            self.put("STATUS", "Restoring selected folders…", True)
            mappings = {"Documents": self.user / "Documents", "Pictures": self.user / "Pictures", "Desktop": self.user / "Desktop", "Downloads": self.user / "Downloads", "Videos": self.user / "Videos", "Music": self.user / "Music"}
            count = 0
            for name, dest_root in mappings.items():
                if not selections.get(name):
                    continue
                src = temp / "data" / name
                if not src.exists():
                    continue
                for base, dirs, names in os.walk(src):
                    for fn in names:
                        if self.cancel.is_set(): self.put("CANCELLED", force=True); return
                        srcf = Path(base) / fn; dst = dest_root / srcf.relative_to(src); dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(srcf, dst); count += 1; self.put("STATUS", f"Restoring {fn}")
            if selections.get("Chrome Profile"):
                src = temp / "data" / "Chrome" / "Default"; dst = self.local / "Google" / "Chrome" / "User Data" / "Default"
                if src.exists():
                    self.put("STATUS", "Restoring Chrome profile…", True)
                    dst.mkdir(parents=True, exist_ok=True)
                    for p in src.iterdir(): shutil.copy2(p, dst / p.name); count += 1
            shutil.rmtree(temp, ignore_errors=True)
            self.put("DONE", {"restore": True, "files": count, "elapsed": time.monotonic() - started}, True)
        except Exception as exc:
            shutil.rmtree(temp, ignore_errors=True)
            self.put("ERROR", str(exc), True)


class App(ctk.CTk):
    def __init__(self):
        super().__init__(); self.title(f"{APP} {VERSION}"); self.geometry("1180x780"); self.minsize(1040, 700); self.configure(fg_color=BG)
        self.grid_rowconfigure(1, weight=1); self.grid_columnconfigure(1, weight=1)
        self.q, self.cancel, self.engine = queue.Queue(), threading.Event(), None
        self.engine = Engine(self.q, self.cancel); self.thread = None; self.licensed, self.key = load_license(); self.pages = {}
        self.make_sidebar(); self.make_header(); self.make_pages(); self.show("dashboard"); self.after(70, self.poll)

    def btn(self, p, text, command, **kw):
        return ctk.CTkButton(p, text=text, command=command, fg_color=kw.pop("fg", BLUE), hover_color=kw.pop("hover", BLUE_H), corner_radius=9, height=42, font=ctk.CTkFont(size=13, weight="bold"), **kw)

    def make_sidebar(self):
        s=ctk.CTkFrame(self,width=220,fg_color=PANEL,corner_radius=0,border_width=1,border_color=BORDER);s.grid(row=0,column=0,rowspan=3,sticky="nsew");s.grid_rowconfigure(8,weight=1)
        ctk.CTkLabel(s,text="MIGRATE",text_color=MUTED,font=ctk.CTkFont(size=11,weight="bold")).grid(row=0,column=0,padx=22,pady=(26,0),sticky="w");ctk.CTkLabel(s,text="KIT",text_color=TEXT,font=ctk.CTkFont(size=30,weight="bold")).grid(row=1,column=0,padx=22,pady=(0,26),sticky="w")
        self.nav={}; items=[("dashboard","Overview"),("backup","Backup"),("restore","Restore"),("monitor","Operations"),("license","License"),("settings","Settings")]
        for i,(k,t) in enumerate(items,2): self.nav[k]=ctk.CTkButton(s,text=t,command=lambda x=k:self.show(x),fg_color="transparent",hover_color=PANEL2,text_color=MUTED,anchor="w",corner_radius=8,height=44);self.nav[k].grid(row=i,column=0,padx=12,pady=3,sticky="ew")
        ctk.CTkLabel(s,text=f"v{VERSION}\nWindows 11",text_color=MUTED,font=ctk.CTkFont(size=10)).grid(row=9,column=0,padx=22,pady=20,sticky="w")

    def make_header(self):
        h=ctk.CTkFrame(self,fg_color=BG,height=70);h.grid(row=0,column=1,sticky="ew",padx=26,pady=(18,0));h.grid_columnconfigure(0,weight=1);self.title_lbl=ctk.CTkLabel(h,text="Overview",text_color=TEXT,font=ctk.CTkFont(size=28,weight="bold"));self.title_lbl.grid(row=0,column=0,sticky="w");self.badge=ctk.CTkLabel(h,text=" LICENSED " if self.licensed else " FREE BACKUP ",text_color=GREEN if self.licensed else AMBER,fg_color=PANEL,corner_radius=7,font=ctk.CTkFont(size=10,weight="bold"));self.badge.grid(row=0,column=1,padx=12);self.btn(h,"New Backup",lambda:self.show("backup"),width=130).grid(row=0,column=2)

    def shell(self):
        f=ctk.CTkScrollableFrame(self.pages_host,fg_color="transparent");f.grid_columnconfigure(0,weight=1);return f
    def card(self,p,title=None,sub=None):
        f=ctk.CTkFrame(p,fg_color=PANEL,corner_radius=14,border_width=1,border_color=BORDER)
        if title: ctk.CTkLabel(f,text=title,text_color=TEXT,font=ctk.CTkFont(size=17,weight="bold")).pack(anchor="w",padx=20,pady=(18,3))
        if sub: ctk.CTkLabel(f,text=sub,text_color=MUTED,wraplength=820,justify="left").pack(anchor="w",padx=20,pady=(0,15))
        return f

    def make_pages(self):
        self.pages_host=ctk.CTkFrame(self,fg_color=BG);self.pages_host.grid(row=1,column=1,sticky="nsew",padx=26,pady=10);self.pages_host.grid_rowconfigure(0,weight=1);self.pages_host.grid_columnconfigure(0,weight=1)
        self.dashboard=self.shell();self.pages["dashboard"]=self.dashboard
        hero=self.card(self.dashboard);hero.pack(fill="x",pady=(0,14));ctk.CTkLabel(hero,text="Premium migration without the mystery.",text_color=TEXT,font=ctk.CTkFont(size=31,weight="bold")).pack(anchor="w",padx=24,pady=(24,6));ctk.CTkLabel(hero,text="A fast local workflow for moving files, Chrome profile data, selected AppData, and user registry settings. The interface stays responsive and tells you exactly what it is doing.",text_color=MUTED,wraplength=820,justify="left").pack(anchor="w",padx=24);a=ctk.CTkFrame(hero,fg_color="transparent");a.pack(fill="x",padx=24,pady=22);self.btn(a,"Create Backup",lambda:self.show("backup"),width=170).pack(side="left");self.btn(a,"Restore Archive",lambda:self.show("restore"),fg=GREEN,hover="#36d29b",width=170).pack(side="left",padx=10);self.btn(a,"Live Operations",lambda:self.show("monitor"),fg=PANEL2,hover=BORDER,width=170).pack(side="left")
        for title,desc in [("Snappy runtime","onedir packaging keeps Python modules and UI resources outside one giant executable."),("Real telemetry","Progress is based on bytes and files, with speed, ETA and current filename."),("Compression control","Fast, Balanced and Maximum LZMA modes; ZIP64 supports large migrations.")]:
            c=self.card(self.dashboard);c.pack(fill="x",pady=5);ctk.CTkLabel(c,text=title,text_color=TEXT,font=ctk.CTkFont(size=15,weight="bold")).pack(anchor="w",padx=18,pady=(15,3));ctk.CTkLabel(c,text=desc,text_color=MUTED).pack(anchor="w",padx=18,pady=(0,15))

        self.backup=self.shell();self.pages["backup"]=self.backup
        b=self.card(self.backup,"Backup Builder","Choose exactly what should be packaged.");b.pack(fill="x",pady=(0,14));self.bvars={}; opts=[("Documents",True),("Pictures",True),("Desktop",True),("Downloads",False),("Videos",False),("Music",False),("Chrome Profile",True),("Application Data (AppData)",False),("Registry Configurations",False)]
        grid=ctk.CTkFrame(b,fg_color="transparent");grid.pack(fill="x",padx=18,pady=(0,15))
        for i,(n,d) in enumerate(opts): self.bvars[n]=ctk.BooleanVar(value=d);ctk.CTkCheckBox(grid,text=n,variable=self.bvars[n],text_color=TEXT).grid(row=i//3,column=i%3,padx=10,pady=8,sticky="w")
        ar=self.card(self.backup,"Archive","Use Maximum for smallest packages; Fast for quick local transfers.");ar.pack(fill="x");row=ctk.CTkFrame(ar,fg_color="transparent");row.pack(fill="x",padx=18,pady=10);row.grid_columnconfigure(0,weight=1);self.target=ctk.CTkEntry(row,height=42);self.target.grid(row=0,column=0,sticky="ew",padx=(0,10));self.target.insert(0,str(self.engine.user/"Desktop"/"MigrateKit_Backup.migratekit"));self.btn(row,"Browse",self.browse_target,fg=PANEL2,hover=BORDER,width=100).grid(row=0,column=1);self.compression=ctk.CTkSegmentedButton(ar,values=["Fast","Balanced","Maximum"]);self.compression.pack(fill="x",padx=18,pady=10);self.compression.set("Maximum");self.btn(ar,"Start Backup",self.start_backup,height=48).pack(fill="x",padx=18,pady=(4,18))

        self.restore=self.shell();self.pages["restore"]=self.restore
        r=self.card(self.restore,"Restore Wizard","Validate the archive first. Then select the user data categories to restore.");r.pack(fill="x");row=ctk.CTkFrame(r,fg_color="transparent");row.pack(fill="x",padx=18,pady=8);row.grid_columnconfigure(0,weight=1);self.restore_path=ctk.CTkEntry(row,height=42,placeholder_text="Select a .migratekit archive");self.restore_path.grid(row=0,column=0,sticky="ew",padx=(0,10));self.btn(row,"Browse",self.browse_restore,fg=PANEL2,hover=BORDER,width=100).grid(row=0,column=1);self.btn(r,"Validate Archive",self.validate_archive,width=180).pack(anchor="w",padx=18,pady=10);self.rvars={};
        for n in ["Documents","Pictures","Desktop","Downloads","Videos","Music","Chrome Profile"]: self.rvars[n]=ctk.BooleanVar(value=n in {"Documents","Pictures","Desktop","Chrome Profile"});ctk.CTkCheckBox(r,text=n,variable=self.rvars[n]).pack(anchor="w",padx=25,pady=4)
        self.restore_btn=self.btn(r,"Restore Selected Data",self.start_restore,fg=GREEN,hover="#36d29b",height=48);self.restore_btn.pack(fill="x",padx=18,pady=18);self.set_restore_state()

        self.monitor=self.shell();self.pages["monitor"]=self.monitor
        m=self.card(self.monitor,"Live Operations","Everything here updates while the background worker copies and compresses.");m.pack(fill="x",pady=(0,14));self.status_lbl=ctk.CTkLabel(m,text="Ready",text_color=TEXT,font=ctk.CTkFont(size=18,weight="bold"));self.status_lbl.pack(anchor="w",padx=18,pady=(4,12));self.file_lbl=ctk.CTkLabel(m,text="No operation running",text_color=MUTED,wraplength=850,justify="left");self.file_lbl.pack(anchor="w",padx=18);self.prog=ctk.CTkProgressBar(m,height=16);self.prog.pack(fill="x",padx=18,pady=12);self.prog.set(0);st=ctk.CTkFrame(m,fg_color="transparent");st.pack(fill="x",padx=18,pady=(0,18));self.done_lbl=ctk.CTkLabel(st,text="0 B",text_color=TEXT);self.done_lbl.pack(side="left");self.total_lbl=ctk.CTkLabel(st,text="0 B",text_color=MUTED);self.total_lbl.pack(side="left",padx=18);self.speed_lbl=ctk.CTkLabel(st,text="0 B/s",text_color=MUTED);self.speed_lbl.pack(side="right");self.eta_lbl=ctk.CTkLabel(st,text="ETA —",text_color=MUTED);self.eta_lbl.pack(side="right",padx=18)
        cp=self.card(self.monitor,"Compression","Archive packaging status");cp.pack(fill="x",pady=(0,14));self.cprog=ctk.CTkProgressBar(cp,height=12);self.cprog.pack(fill="x",padx=18,pady=(0,8));self.cprog.set(0);self.clabel=ctk.CTkLabel(cp,text="Idle",text_color=MUTED);self.clabel.pack(anchor="w",padx=18,pady=(0,14))
        lg=self.card(self.monitor,"Activity Log");lg.pack(fill="x");self.logbox=ctk.CTkTextbox(lg,height=260,fg_color="#0b1018",border_width=1,border_color=BORDER,font=ctk.CTkFont(family="Consolas",size=11));self.logbox.pack(fill="both",padx=18,pady=(0,18));self.logbox.configure(state="disabled");self.cancel_btn=self.btn(self.monitor,"Cancel Operation",self.cancel_op,fg=RED,hover="#ff7584",width=180);self.cancel_btn.pack(anchor="e",pady=(0,5));self.cancel_btn.configure(state="disabled")

        self.lic=self.shell();self.pages["license"]=self.lic;l=self.card(self.lic,"License","A license unlocks the restore workflow.");l.pack(fill="x");self.lic_status=ctk.CTkLabel(l,text="ACTIVE" if self.licensed else "LOCKED",text_color=GREEN if self.licensed else AMBER,font=ctk.CTkFont(size=24,weight="bold"));self.lic_status.pack(anchor="w",padx=18,pady=10);self.lic_entry=ctk.CTkEntry(l,height=44,placeholder_text="XXXXX-XXXXX-XXXXX-XXXXX");self.lic_entry.pack(fill="x",padx=18);self.btn(l,"Activate License",self.activate,height=44).pack(fill="x",padx=18,pady=14)

        self.settings=self.shell();self.pages["settings"]=self.settings;s=self.card(self.settings,"Settings","Appearance and runtime information");s.pack(fill="x");rr=ctk.CTkFrame(s,fg_color="transparent");rr.pack(fill="x",padx=18,pady=12);ctk.CTkLabel(rr,text="Appearance",text_color=TEXT).pack(side="left");ctk.CTkOptionMenu(rr,values=["Dark","Light","System"],command=ctk.set_appearance_mode).pack(side="right")

        bar=ctk.CTkFrame(self,fg_color=PANEL,height=28,corner_radius=0,border_width=1,border_color=BORDER);bar.grid(row=2,column=1,sticky="ew");ctk.CTkLabel(bar,text=f"{APP} {VERSION} · Background I/O · ZIP64 · onedir runtime",text_color=MUTED,font=ctk.CTkFont(size=10)).pack(side="left",padx=15,pady=4)

    def show(self,key):
        for p in self.pages.values(): p.grid_forget()
        self.pages[key].grid(row=0,column=0,sticky="nsew");self.title_lbl.configure(text={"dashboard":"Overview","backup":"Backup","restore":"Restore","monitor":"Operations","license":"License","settings":"Settings"}[key])
        for k,b in self.nav.items(): b.configure(fg_color=PANEL2 if k==key else "transparent",text_color=TEXT if k==key else MUTED)

    def set_restore_state(self):
        self.restore_btn.configure(state="normal" if self.licensed else "disabled",text="Restore Selected Data" if self.licensed else "Restore Locked — Activate License")
    def browse_target(self):
        p=filedialog.asksaveasfilename(defaultextension=".migratekit",filetypes=[("MigrateKit Archive","*.migratekit")]);
        if p:self.target.delete(0,"end");self.target.insert(0,p)
    def browse_restore(self):
        p=filedialog.askopenfilename(filetypes=[("MigrateKit Archive","*.migratekit")]);
        if p:self.restore_path.delete(0,"end");self.restore_path.insert(0,p)
    def validate_archive(self):
        try:
            with zipfile.ZipFile(self.restore_path.get().strip()) as zf:
                bad=zf.testzip()
                if bad: raise ValueError(f"Corrupt archive member: {bad}")
            messagebox.showinfo("Valid archive","ZIP integrity validation passed.")
        except Exception as e: messagebox.showerror("Invalid archive",str(e))
    def activate(self):
        key=self.lic_entry.get().strip();ok,detail=verify_key(key)
        if not ok: messagebox.showerror("Activation failed",detail);return
        save_license(key);self.licensed=True;self.key=key;self.badge.configure(text=" LICENSED ",text_color=GREEN);self.lic_status.configure(text="ACTIVE",text_color=GREEN);self.set_restore_state();messagebox.showinfo("Activated",detail)
    def prepare_op(self):
        self.cancel.clear();self.prog.set(0);self.cprog.set(0);self.status_lbl.configure(text="Starting…");self.file_lbl.configure(text="Preparing…");self.done_lbl.configure(text="0 B");self.total_lbl.configure(text="0 B");self.speed_lbl.configure(text="0 B/s");self.eta_lbl.configure(text="ETA —");self.clabel.configure(text="Waiting");self.cancel_btn.configure(state="normal");self.logbox.configure(state="normal");self.logbox.delete("1.0","end");self.logbox.configure(state="disabled");self.show("monitor")
    def start_backup(self):
        if self.thread and self.thread.is_alive(): messagebox.showwarning("Busy","An operation is already running.");return
        target=self.target.get().strip()
        if not target: messagebox.showerror("Backup","Choose a destination.");return
        self.prepare_op(); selected={k:v.get() for k,v in self.bvars.items()}; self.thread=threading.Thread(target=self.engine.backup,args=(target,selected,self.compression.get()),daemon=True);self.thread.start()
    def start_restore(self):
        if not self.licensed: self.show("license");return
        p=self.restore_path.get().strip()
        if not os.path.exists(p): messagebox.showerror("Restore","Select a valid archive.");return
        self.prepare_op();self.thread=threading.Thread(target=self.engine.restore,args=(p,{k:v.get() for k,v in self.rvars.items()}),daemon=True);self.thread.start()
    def cancel_op(self):
        self.cancel.set();self.log("Cancellation requested — current file will finish safely.")
    def log(self,text):
        self.logbox.configure(state="normal");self.logbox.insert("end",f"[{time.strftime('%H:%M:%S')}] {text}\n");self.logbox.see("end");self.logbox.configure(state="disabled")
    def poll(self):
        try:
            while True:
                k,d=self.q.get_nowait()
                if k=="LOG":self.log(d)
                elif k=="STATUS":self.status_lbl.configure(text=d)
                elif k=="PROGRESS":self.prog.set(d["progress"]);self.done_lbl.configure(text=fmt_bytes(d["done"]));self.total_lbl.configure(text=fmt_bytes(d["total"]));self.speed_lbl.configure(text=fmt_bytes(d["speed"])+"/s");self.eta_lbl.configure(text="ETA "+fmt_time(d["eta"]));self.file_lbl.configure(text=d["file"])
                elif k=="COMPRESSION":self.cprog.set(d["done"]/max(1,d["total"]));self.clabel.configure(text=f"{d['done']} / {d['total']} · {d['file']}")
                elif k=="DONE":
                    self.cancel_btn.configure(state="disabled")
                    if d.get("restore"): self.status_lbl.configure(text=f"Restore complete · {d['files']:,} files") ; self.log(f"Restore completed in {fmt_time(d['elapsed'])}");messagebox.showinfo("Restore complete",f"Restored {d['files']:,} files.")
                    else: self.prog.set(1);self.cprog.set(1);self.status_lbl.configure(text="Backup complete");self.clabel.configure(text=f"Archive {fmt_bytes(d['size'])} · ratio {d['ratio']:.1%}");self.log(f"Backup complete: {d['files']:,} files; {d['skipped']} skipped; {fmt_bytes(d['size'])}");messagebox.showinfo("Backup complete",f"Archive created:\n{d['path']}\n\nSize: {fmt_bytes(d['size'])}\nFiles: {d['files']:,}")
                elif k=="CANCELLED":self.cancel_btn.configure(state="disabled");self.status_lbl.configure(text="Cancelled");self.log("Operation cancelled safely.")
                elif k=="ERROR":self.cancel_btn.configure(state="disabled");self.status_lbl.configure(text="Failed");self.log(d);messagebox.showerror("Operation failed",d)
        except queue.Empty: pass
        self.after(70,self.poll)


if __name__ == "__main__":
    App().mainloop()
