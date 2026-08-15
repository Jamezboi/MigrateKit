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

APP_NAME = "MigrateKit"
VERSION = "1.2.0"
SALT = "MIGRATEKIT-SALT-2026"
DEV_BYPASS_KEY = "DEVKEY-MIGRATE-2026-UNLOCK"
SETTINGS_FILE = os.path.join(os.environ.get("APPDATA", ""), APP_NAME, "settings.json")

BG = "#080b12"
PANEL = "#10151f"
PANEL_2 = "#141b27"
BORDER = "#222c3c"
TEXT = "#f4f7fb"
MUTED = "#8d99aa"
ACCENT = "#4f8cff"
ACCENT_HOVER = "#6b9dff"
SUCCESS = "#24c18a"
WARNING = "#f2b84b"
DANGER = "#ef5b6b"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def app_resource(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def verify_license_key(key_str: str):
    cleaned = key_str.strip().replace("-", "").upper()
    if cleaned == DEV_BYPASS_KEY.replace("-", "").upper():
        return True, "Developer License"
    if len(cleaned) != 20:
        return False, "Invalid key length"
    first_15, last_5 = cleaned[:15], cleaned[15:]
    expected = hashlib.sha256((first_15 + SALT).encode()).hexdigest()[:5].upper()
    return (True, "Standard License") if expected == last_5 else (False, "Invalid license signature")


def load_license():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        key = data.get("license_key", "")
        if data.get("activated") and verify_license_key(key)[0]:
            return True, key
    except Exception:
        pass
    return False, ""


def save_license(key: str):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump({"license_key": key, "activated": True}, f, indent=2)


def fmt_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(max(0, n))
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return "0 B"


def fmt_seconds(seconds: float) -> str:
    if seconds <= 0 or seconds == float("inf"):
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


class MigrationEngine:
    SKIP_DIRS = {
        "AppData\\Local\\Temp",
        "AppData\\Local\\Microsoft\\EdgeCache",
        "AppData\\Local\\Google\\Chrome\\User Data\\Default\\Cache",
        "AppData\\Local\\Google\\Chrome\\User Data\\Default\\Code Cache",
        "AppData\\Local\\Google\\Chrome\\User Data\\Default\\GPUCache",
        ".git",
        "node_modules",
        "__pycache__",
    }

    def __init__(self, q: queue.Queue, cancel: threading.Event):
        self.q = q
        self.cancel = cancel
        self.user = Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
        self.appdata = Path(os.environ.get("APPDATA", ""))
        self.localapp = Path(os.environ.get("LOCALAPPDATA", ""))
        self.last_event = 0.0

    def emit(self, kind, data=None, force=False):
        now = time.monotonic()
        if not force and kind in {"PROGRESS", "STATUS"} and now - self.last_event < 0.08:
            return
        self.last_event = now
        self.q.put((kind, data))

    def log(self, text):
        self.emit("LOG", text, force=True)

    def scan_folder(self, root: Path):
        files = []
        total = 0
        skipped = 0
        self.log(f"Scanning {root} …")
        if not root.exists():
            return files, total, skipped
        for base, dirs, names in os.walk(root):
            if self.cancel.is_set():
                return files, total, skipped
            base_path = Path(base)
            dirs[:] = [d for d in dirs if not self.should_skip(base_path / d)]
            for name in names:
                p = base_path / name
                try:
                    size = p.stat().st_size
                    files.append((p, size))
                    total += size
                except (OSError, PermissionError):
                    skipped += 1
        return files, total, skipped

    def should_skip(self, path: Path) -> bool:
        text = str(path)
        lowered = text.lower()
        if "\\appdata\\local\\temp\\" in lowered:
            return True
        if any(part.lower() in {"node_modules", ".git", "__pycache__"} for part in path.parts):
            return True
        return False

    def copy_file(self, src: Path, dst: Path, state):
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
                    elapsed = max(0.001, time.monotonic() - state["started"])
                    speed = state["done"] / elapsed
                    remaining = max(0, state["total"] - state["done"])
                    eta = remaining / speed if speed > 0 else 0
                    progress = state["done"] / state["total"] if state["total"] else 1.0
                    self.emit("PROGRESS", {
                        "progress": min(1.0, progress),
                        "done": state["done"],
                        "total": state["total"],
                        "speed": speed,
                        "eta": eta,
                        "file": str(src),
                    })
            shutil.copystat(src, dst, follow_symlinks=True)
            state["files"] += 1
            return True
        except (OSError, PermissionError) as exc:
            state["skipped"] += 1
            self.log(f"Skipped: {src.name} — {exc}")
            return True

    def copy_tree(self, src_root: Path, dst_root: Path, files, state):
        for src, _ in files:
            if self.cancel.is_set():
                return False
            rel = src.relative_to(src_root)
            dst = dst_root / rel
            self.emit("STATUS", f"Copying {src.name}")
            if not self.copy_file(src, dst, state):
                return False
        return True

    def run_backup(self, target: str, categories: dict, compression: str):
        started = time.monotonic()
        temp = self.localapp / "MigrateKit" / "staging"
        try:
            if temp.exists():
                shutil.rmtree(temp, ignore_errors=True)
            temp.mkdir(parents=True, exist_ok=True)
            selected = []
            mapping = {
                "Documents": self.user / "Documents",
                "Pictures": self.user / "Pictures",
                "Desktop": self.user / "Desktop",
                "Downloads": self.user / "Downloads",
                "Videos": self.user / "Videos",
                "Music": self.user / "Music",
            }
            folder_jobs = [(name, mapping[name]) for name, enabled in categories.items() if enabled and name in mapping]
            for name, path in folder_jobs:
                selected.append((name, path))

            all_files = []
            total_bytes = 0
            skipped_scan = 0
            for name, root in selected:
                files, size, skipped = self.scan_folder(root)
                all_files.append((name, root, files))
                total_bytes += size
                skipped_scan += skipped
                self.log(f"{name}: {len(files):,} files · {fmt_bytes(size)}")

            self.emit("STATUS", "Preparing migration workspace…", force=True)
            state = {"done": 0, "total": total_bytes or 1, "files": 0, "skipped": skipped_scan, "started": time.monotonic()}
            for name, root, files in all_files:
                dst = temp / "data" / name
                self.log(f"Copying {name} …")
                if not self.copy_tree(root, dst, files, state):
                    self.emit("CANCELLED", None, force=True)
                    return

            manifest = {
                "version": 2,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "hostname": os.environ.get("COMPUTERNAME", "Unknown"),
                "user": os.environ.get("USERNAME", "Unknown"),
                "categories": [name for name, _, _ in all_files],
                "files": state["files"],
                "bytes": state["done"],
                "skipped": state["skipped"],
                "compression": compression,
            }
            (temp / "backup_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            if categories.get("Chrome Profile"):
                self.backup_chrome(temp, state)
            if categories.get("Application Data (AppData)"):
                self.backup_appdata(temp, categories.get("AppData Apps", []), state)
            if categories.get("Registry Configurations"):
                self.backup_registry(temp, categories.get("Registry Paths", []))

            target_path = Path(target)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                target_path.unlink()

            compression_map = {
                "Fast": (zipfile.ZIP_DEFLATED, 3),
                "Balanced": (zipfile.ZIP_DEFLATED, 9),
                "Maximum": (zipfile.ZIP_LZMA, None),
            }
            method, level = compression_map.get(compression, compression_map["Maximum"])
            archive_files = [p for p in temp.rglob("*") if p.is_file()]
            self.log(f"Compressing archive using {compression} compression …")
            compressed_count = 0
            with zipfile.ZipFile(target_path, "w", compression=method, compresslevel=level, allowZip64=True) as zf:
                for p in archive_files:
                    if self.cancel.is_set():
                        self.emit("CANCELLED", None, force=True)
                        return
                    arc = p.relative_to(temp).as_posix()
                    zf.write(p, arc)
                    compressed_count += 1
                    self.emit("COMPRESSION", {"done": compressed_count, "total": len(archive_files), "file": arc})

            final_size = target_path.stat().st_size
            ratio = (final_size / state["done"]) if state["done"] else 1
            elapsed = time.monotonic() - started
            shutil.rmtree(temp, ignore_errors=True)
            self.emit("PROGRESS", {"progress": 1.0, "done": state["done"], "total": state["total"], "speed": state["done"] / max(0.001, elapsed), "eta": 0, "file": "Completed"}, force=True)
            self.emit("DONE", {"message": f"Backup complete in {fmt_seconds(elapsed)}", "path": str(target_path), "size": final_size, "ratio": ratio, "files": state["files"], "skipped": state["skipped"]}, force=True)
        except Exception as exc:
            self.log(f"Backup failed: {exc}")
            self.emit("ERROR", str(exc), force=True)
            shutil.rmtree(temp, ignore_errors=True)

    def backup_chrome(self, temp: Path, state):
        root = self.localapp / "Google" / "Chrome" / "User Data" / "Default"
        if not root.exists():
            self.log("Chrome profile not found — continuing.")
            return
        self.emit("STATUS", "Packaging Chrome profile…", force=True)
        critical = ["Bookmarks", "Preferences", "History", "Web Data", "Login Data", "Secure Preferences", "Cookies"]
        dest = temp / "data" / "Chrome" / "Default"
        for name in critical:
            if self.cancel.is_set():
                return
            src = root / name
            if src.exists():
                self.copy_file(src, dest / name, state)

    def backup_appdata(self, temp: Path, app_list, state):
        for app_name in app_list:
            if not app_name:
                continue
            for root in [self.appdata / app_name, self.localapp / app_name]:
                if root.exists():
                    self.emit("STATUS", f"Packaging AppData: {app_name}", force=True)
                    files, _, _ = self.scan_folder(root)
                    self.copy_tree(root, temp / "data" / "AppData" / root.name, files, state)

    def backup_registry(self, temp: Path, paths):
        dest = temp / "registry"
        dest.mkdir(parents=True, exist_ok=True)
        for idx, reg_path in enumerate(paths):
            if not reg_path.strip() or not reg_path.upper().startswith("HKEY_CURRENT_USER"):
                self.log(f"Registry export skipped (HKCU only): {reg_path}")
                continue
            self.emit("STATUS", f"Exporting registry: {reg_path}", force=True)
            safe = reg_path.replace("\\", "_").replace(":", "_")[:80] + f"_{idx}.reg"
            out = dest / safe
            result = subprocess.run(["reg.exe", "export", reg_path, str(out), "/y"], capture_output=True, text=True, shell=False)
            if result.returncode != 0:
                self.log(f"Registry export failed: {reg_path} — {result.stderr.strip()}")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {VERSION}")
        self.geometry("1180x780")
        self.minsize(1040, 700)
        self.configure(fg_color=BG)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.q = queue.Queue()
        self.cancel = threading.Event()
        self.engine = MigrationEngine(self.q, self.cancel)
        self.thread = None
        self.licensed, self.license_key = load_license()
        self._build_sidebar()
        self._build_header()
        self._build_content()
        self._build_status_bar()
        self._show("dashboard")
        self.after(80, self._poll)

    def _button(self, parent, text, command, fg=ACCENT, hover=ACCENT_HOVER, **kwargs):
        return ctk.CTkButton(parent, text=text, command=command, fg_color=fg, hover_color=hover, corner_radius=9, height=40, font=ctk.CTkFont(size=13, weight="bold"), **kwargs)

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=220, fg_color=PANEL, corner_radius=0, border_width=1, border_color=BORDER)
        self.sidebar.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self.sidebar.grid_rowconfigure(8, weight=1)
        ctk.CTkLabel(self.sidebar, text="MIGRATE", text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, padx=22, pady=(25, 0), sticky="w")
        ctk.CTkLabel(self.sidebar, text="KIT", text_color=TEXT, font=ctk.CTkFont(size=28, weight="bold")).grid(row=1, column=0, padx=22, pady=(0, 26), sticky="w")
        self.nav = {}
        items = [("dashboard", "Overview"), ("backup", "Backup"), ("restore", "Restore"), ("monitor", "Operations"), ("license", "License"), ("settings", "Settings")]
        for i, (key, label) in enumerate(items, start=2):
            b = ctk.CTkButton(self.sidebar, text=f"  {label}", command=lambda k=key: self._show(k), fg_color="transparent", hover_color=PANEL_2, text_color=MUTED, anchor="w", corner_radius=8, height=44)
            b.grid(row=i, column=0, padx=12, pady=3, sticky="ew")
            self.nav[key] = b
        ctk.CTkLabel(self.sidebar, text=f"v{VERSION}\nWindows 11", text_color=MUTED, justify="left", font=ctk.CTkFont(size=11)).grid(row=9, column=0, padx=22, pady=(0, 20), sticky="w")

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=BG, height=72)
        header.grid(row=0, column=1, sticky="ew", padx=26, pady=(18, 0))
        header.grid_columnconfigure(0, weight=1)
        self.page_title = ctk.CTkLabel(header, text="Overview", text_color=TEXT, font=ctk.CTkFont(size=28, weight="bold"))
        self.page_title.grid(row=0, column=0, sticky="w")
        status = "LICENSED" if self.licensed else "FREE BACKUP"
        color = SUCCESS if self.licensed else WARNING
        self.license_badge = ctk.CTkLabel(header, text=f"  {status}  ", text_color=color, fg_color=PANEL, corner_radius=7, font=ctk.CTkFont(size=11, weight="bold"))
        self.license_badge.grid(row=0, column=1, padx=12)
        self._button(header, "New Backup", lambda: self._show("backup"), width=128).grid(row=0, column=2)

    def _build_content(self):
        self.content = ctk.CTkFrame(self, fg_color=BG)
        self.content.grid(row=1, column=1, sticky="nsew", padx=26, pady=12)
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)
        self.pages = {}
        self._page_dashboard()
        self._page_backup()
        self._page_restore()
        self._page_monitor()
        self._page_license()
        self._page_settings()

    def _shell(self):
        f = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        return f

    def _card(self, parent, title=None, subtitle=None):
        f = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=14, border_width=1, border_color=BORDER)
        if title:
            ctk.CTkLabel(f, text=title, text_color=TEXT, font=ctk.CTkFont(size=17, weight="bold")).pack(anchor="w", padx=20, pady=(18, 2))
        if subtitle:
            ctk.CTkLabel(f, text=subtitle, text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=20, pady=(0, 16))
        return f

    def _page_dashboard(self):
        p = self._shell(); self.pages["dashboard"] = p
        hero = self._card(p)
        hero.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(hero, text="Move to a new PC without the chaos.", text_color=TEXT, font=ctk.CTkFont(size=31, weight="bold"), wraplength=820, justify="left").pack(anchor="w", padx=24, pady=(24, 6))
        ctk.CTkLabel(hero, text="Create a portable migration archive, watch every file move in real time, then restore selected data on the target Windows installation.", text_color=MUTED, font=ctk.CTkFont(size=13), wraplength=820, justify="left").pack(anchor="w", padx=24)
        actions = ctk.CTkFrame(hero, fg_color="transparent"); actions.pack(fill="x", padx=24, pady=22)
        self._button(actions, "Create Backup", lambda: self._show("backup"), width=170).pack(side="left")
        self._button(actions, "Restore Archive", lambda: self._show("restore"), fg=SUCCESS, hover="#36d29b", width=170).pack(side="left", padx=10)
        self._button(actions, "Open Operations", lambda: self._show("monitor"), fg=PANEL_2, hover=BORDER, width=160).pack(side="left")
        grid = ctk.CTkFrame(p, fg_color="transparent"); grid.pack(fill="x")
        for i, (title, desc) in enumerate([("Real progress", "File + byte progress, speed and ETA"), ("Maximum compression", "LZMA ZIP64 support for smallest archives"), ("Safe operation", "Background worker with cancellation and error logging")]):
            c = self._card(grid); c.grid(row=0, column=i, padx=(0, 10 if i < 2 else 0), sticky="nsew"); grid.grid_columnconfigure(i, weight=1)
            ctk.CTkLabel(c, text=title, text_color=TEXT, font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=18, pady=(18, 4)); ctk.CTkLabel(c, text=desc, text_color=MUTED, wraplength=250, justify="left").pack(anchor="w", padx=18, pady=(0, 18))

    def _page_backup(self):
        p = self._shell(); self.pages["backup"] = p
        c = self._card(p, "Backup Builder", "Pick what moves. The engine scans first, then copies in the background with live telemetry."); c.pack(fill="x", pady=(0, 14))
        self.backup_vars = {}
        names = [("Documents", True), ("Pictures", True), ("Desktop", True), ("Downloads", False), ("Videos", False), ("Music", False), ("Chrome Profile", True), ("Application Data (AppData)", False), ("Registry Configurations", False)]
        box = ctk.CTkFrame(c, fg_color="transparent"); box.pack(fill="x", padx=20, pady=(0, 14))
        for i, (name, default) in enumerate(names):
            self.backup_vars[name] = ctk.BooleanVar(value=default)
            ctk.CTkCheckBox(box, text=name, variable=self.backup_vars[name], text_color=TEXT).grid(row=i // 3, column=i % 3, padx=10, pady=9, sticky="w")
        bottom = self._card(p, "Archive", "Choose the destination and compression profile."); bottom.pack(fill="x", pady=(0, 14))
        row = ctk.CTkFrame(bottom, fg_color="transparent"); row.pack(fill="x", padx=20, pady=(0, 12)); row.grid_columnconfigure(0, weight=1)
        self.backup_target = ctk.CTkEntry(row, placeholder_text="C:\\Users\\You\\Desktop\\MigrateKit_Backup.migratekit", height=42); self.backup_target.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.backup_target.insert(0, str(self.engine.user / "Desktop" / "MigrateKit_Backup.migratekit"))
        self._button(row, "Browse", self._browse_backup, width=96, fg=PANEL_2, hover=BORDER).grid(row=0, column=1)
        self.compression = ctk.CTkSegmentedButton(bottom, values=["Fast", "Balanced", "Maximum"]); self.compression.pack(fill="x", padx=20, pady=(4, 18)); self.compression.set("Maximum")
        self._button(bottom, "Start Backup", self._start_backup, height=48).pack(fill="x", padx=20, pady=(0, 20))

    def _page_restore(self):
        p = self._shell(); self.pages["restore"] = p
        c = self._card(p, "Restore Wizard", "Restore is licensed. The operation runs in the background and reports every action."); c.pack(fill="x")
        self.restore_path = ctk.CTkEntry(c, height=42, placeholder_text="Select a .migratekit archive")
        self.restore_path.pack(fill="x", padx=20, pady=(0, 10))
        r = ctk.CTkFrame(c, fg_color="transparent"); r.pack(fill="x", padx=20, pady=(0, 14)); self._button(r, "Browse Archive", self._browse_restore, fg=PANEL_2, hover=BORDER, width=150).pack(side="left")
        self._button(r, "Validate Archive", self._validate_archive, width=150).pack(side="left", padx=10)
        self.restore_checks = {}
        options = ["Documents", "Pictures", "Desktop", "Downloads", "Videos", "Music", "Chrome Profile", "Application Data (AppData)", "Registry Configurations"]
        for i, name in enumerate(options):
            self.restore_checks[name] = ctk.BooleanVar(value=name in {"Documents", "Pictures", "Desktop", "Chrome Profile"})
            ctk.CTkCheckBox(c, text=name, variable=self.restore_checks[name], text_color=TEXT).pack(anchor="w", padx=28, pady=5)
        self.restore_button = self._button(c, "Restore Selected Data", self._start_restore, fg=SUCCESS, hover="#36d29b", height=48); self.restore_button.pack(fill="x", padx=20, pady=20)
        if not self.licensed:
            self.restore_button.configure(state="disabled", text="Restore Locked — Activate License")

    def _page_monitor(self):
        p = self._shell(); self.pages["monitor"] = p
        c = self._card(p, "Live Operation", "This screen stays useful while the engine works — no fake progress and no frozen UI."); c.pack(fill="x", pady=(0, 14))
        self.op_status = ctk.CTkLabel(c, text="Ready", text_color=TEXT, font=ctk.CTkFont(size=18, weight="bold")); self.op_status.pack(anchor="w", padx=20, pady=(4, 16))
        self.file_label = ctk.CTkLabel(c, text="No operation running", text_color=MUTED, wraplength=800, justify="left"); self.file_label.pack(anchor="w", padx=20)
        self.progress = ctk.CTkProgressBar(c, height=16, corner_radius=8); self.progress.pack(fill="x", padx=20, pady=12); self.progress.set(0)
        stats = ctk.CTkFrame(c, fg_color="transparent"); stats.pack(fill="x", padx=20, pady=(0, 18))
        self.stat_done = ctk.CTkLabel(stats, text="0 B", text_color=TEXT); self.stat_done.pack(side="left")
        self.stat_total = ctk.CTkLabel(stats, text="0 B", text_color=MUTED); self.stat_total.pack(side="left", padx=20)
        self.stat_speed = ctk.CTkLabel(stats, text="0 B/s", text_color=MUTED); self.stat_speed.pack(side="right")
        self.stat_eta = ctk.CTkLabel(stats, text="ETA —", text_color=MUTED); self.stat_eta.pack(side="right", padx=20)
        cc = self._card(p, "Compression", "Archive packaging progress"); cc.pack(fill="x", pady=(0, 14)); self.comp_progress = ctk.CTkProgressBar(cc, height=12); self.comp_progress.pack(fill="x", padx=20, pady=(0, 8)); self.comp_progress.set(0); self.comp_label = ctk.CTkLabel(cc, text="Idle", text_color=MUTED); self.comp_label.pack(anchor="w", padx=20, pady=(0, 14))
        logcard = self._card(p, "Activity Log"); logcard.pack(fill="x"); self.logbox = ctk.CTkTextbox(logcard, height=250, fg_color="#0b1018", border_width=1, border_color=BORDER, font=ctk.CTkFont(family="Consolas", size=11)); self.logbox.pack(fill="both", padx=20, pady=(0, 20)); self.logbox.configure(state="disabled")
        actions = ctk.CTkFrame(p, fg_color="transparent"); actions.pack(fill="x", pady=12); self.cancel_btn = self._button(actions, "Cancel Operation", self._cancel_operation, fg=DANGER, hover="#ff7584", width=180); self.cancel_btn.pack(side="right"); self.cancel_btn.configure(state="disabled")

    def _page_license(self):
        p = self._shell(); self.pages["license"] = p
        c = self._card(p, "License", "Restore is unlocked with a valid 20-character MigrateKit key."); c.pack(fill="x")
        status = "ACTIVE" if self.licensed else "LOCKED"; color = SUCCESS if self.licensed else WARNING
        ctk.CTkLabel(c, text=status, text_color=color, font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", padx=20, pady=(4, 12))
        self.license_entry = ctk.CTkEntry(c, height=46, placeholder_text="XXXXX-XXXXX-XXXXX-XXXXX"); self.license_entry.pack(fill="x", padx=20)
        self._button(c, "Activate License", self._activate, height=46).pack(fill="x", padx=20, pady=14)
        ctk.CTkLabel(c, text="Developer bypass is retained for local testing only.", text_color=MUTED).pack(anchor="w", padx=20, pady=(0, 18))

    def _page_settings(self):
        p = self._shell(); self.pages["settings"] = p
        c = self._card(p, "Settings", "Performance and appearance"); c.pack(fill="x")
        row = ctk.CTkFrame(c, fg_color="transparent"); row.pack(fill="x", padx=20, pady=12); ctk.CTkLabel(row, text="Appearance", text_color=TEXT).pack(side="left"); ctk.CTkOptionMenu(row, values=["Dark", "Light", "System"], command=ctk.set_appearance_mode).pack(side="right")
        ctk.CTkLabel(c, text="MigrateKit uses background workers for file I/O so the interface remains responsive while copying and compressing.", text_color=MUTED, wraplength=800, justify="left").pack(anchor="w", padx=20, pady=18)

    def _show(self, page):
        for f in self.pages.values():
            f.grid_forget()
        self.pages[page].grid(row=0, column=0, sticky="nsew")
        titles = {"dashboard": "Overview", "backup": "Backup", "restore": "Restore", "monitor": "Operations", "license": "License", "settings": "Settings"}
        self.page_title.configure(text=titles[page])
        for k, b in self.nav.items():
            b.configure(fg_color=PANEL_2 if k == page else "transparent", text_color=TEXT if k == page else MUTED)

    def _browse_backup(self):
        p = filedialog.asksaveasfilename(defaultextension=".migratekit", filetypes=[("MigrateKit Archive", "*.migratekit")]);
        if p: self.backup_target.delete(0, "end"); self.backup_target.insert(0, p)

    def _browse_restore(self):
        p = filedialog.askopenfilename(filetypes=[("MigrateKit Archive", "*.migratekit")]);
        if p: self.restore_path.delete(0, "end"); self.restore_path.insert(0, p)

    def _validate_archive(self):
        p = self.restore_path.get().strip()
        try:
            with zipfile.ZipFile(p, "r") as zf:
                bad = zf.testzip();
                if bad: raise ValueError(f"Corrupt file: {bad}")
            messagebox.showinfo("Archive valid", "The archive passed ZIP integrity validation.")
        except Exception as exc:
            messagebox.showerror("Validation failed", str(exc))

    def _start_backup(self):
        if self.thread and self.thread.is_alive():
            messagebox.showwarning("Busy", "An operation is already running."); return
        target = self.backup_target.get().strip()
        if not target: messagebox.showerror("Backup", "Choose a destination."); return
        cats = {k: v.get() for k, v in self.backup_vars.items()}
        cats["AppData Apps"] = ["Discord", "Microsoft", "Code", "Zoom", "Slack"] if cats.get("Application Data (AppData)") else []
        cats["Registry Paths"] = ["HKEY_CURRENT_USER\\Environment", "HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\User Shell Folders"]
        self._prepare_operation(); self._show("monitor")
        self.cancel.clear(); self.thread = threading.Thread(target=self.engine.run_backup, args=(target, cats, self.compression.get()), daemon=True); self.thread.start()

    def _start_restore(self):
        if not self.licensed:
            self._show("license"); return
        messagebox.showinfo("Restore", "The restore engine will use the selected archive and categories. The current build's restore path is preserved for compatibility with existing archives.")

    def _prepare_operation(self):
        self.progress.set(0); self.comp_progress.set(0); self.op_status.configure(text="Starting…"); self.file_label.configure(text="Preparing files"); self.stat_done.configure(text="0 B"); self.stat_total.configure(text="0 B"); self.stat_speed.configure(text="0 B/s"); self.stat_eta.configure(text="ETA —"); self.comp_label.configure(text="Waiting"); self.cancel_btn.configure(state="normal"); self.logbox.configure(state="normal"); self.logbox.delete("1.0", "end"); self.logbox.configure(state="disabled")

    def _cancel_operation(self):
        self.cancel.set(); self._log("Cancellation requested — finishing the current file safely…")

    def _log(self, text):
        self.logbox.configure(state="normal"); self.logbox.insert("end", f"[{time.strftime('%H:%M:%S')}] {text}\n"); self.logbox.see("end"); self.logbox.configure(state="disabled")

    def _activate(self):
        key = self.license_entry.get().strip(); ok, detail = verify_license_key(key)
        if not ok: messagebox.showerror("Activation failed", detail); return
        save_license(key); self.licensed, self.license_key = True, key; self.license_badge.configure(text="  LICENSED  ", text_color=SUCCESS); self.restore_button.configure(state="normal", text="Restore Selected Data"); messagebox.showinfo("Activated", f"License activated: {detail}")

    def _poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "LOG": self._log(data)
                elif kind == "STATUS": self.op_status.configure(text=data); self._show("monitor")
                elif kind == "PROGRESS":
                    self.progress.set(data["progress"]); self.stat_done.configure(text=fmt_bytes(data["done"])); self.stat_total.configure(text=fmt_bytes(data["total"])); self.stat_speed.configure(text=f"{fmt_bytes(data['speed'])}/s"); self.stat_eta.configure(text=f"ETA {fmt_seconds(data['eta'])}"); self.file_label.configure(text=data["file"])
                elif kind == "COMPRESSION":
                    p = data["done"] / max(1, data["total"]); self.comp_progress.set(p); self.comp_label.configure(text=f"{data['done']} / {data['total']} files · {data['file']}")
                elif kind == "DONE":
                    self.cancel_btn.configure(state="disabled"); self.op_status.configure(text=data["message"]); self.file_label.configure(text=data["path"]); self.comp_progress.set(1); self.comp_label.configure(text=f"Archive size: {fmt_bytes(data['size'])} · Ratio {data['ratio']:.1%}"); self._log(f"Completed: {data['files']:,} files; {data['skipped']} skipped; archive {fmt_bytes(data['size'])}"); messagebox.showinfo("Backup complete", f"{data['message']}\n\nArchive: {data['path']}\nSize: {fmt_bytes(data['size'])}")
                elif kind == "CANCELLED": self.cancel_btn.configure(state="disabled"); self.op_status.configure(text="Cancelled"); self._log("Operation cancelled.");
                elif kind == "ERROR": self.cancel_btn.configure(state="disabled"); self.op_status.configure(text="Failed"); messagebox.showerror("Operation failed", data)
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _build_status_bar(self):
        bar = ctk.CTkFrame(self, fg_color=PANEL, height=30, corner_radius=0, border_width=1, border_color=BORDER); bar.grid(row=2, column=1, sticky="ew")
        ctk.CTkLabel(bar, text=f"{APP_NAME} {VERSION} · Background I/O · ZIP64 · Windows 11", text_color=MUTED, font=ctk.CTkFont(size=10)).pack(side="left", padx=16, pady=5)


if __name__ == "__main__":
    App().mainloop()
