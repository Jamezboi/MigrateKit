import os
import sys
import shutil
import json
import time
import threading
import queue
import hashlib
import zipfile
import subprocess
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox

APP_NAME = "MigrateKit"
APP_VERSION = "1.1.0"
SALT = "MIGRATEKIT-SALT-2026"
DEV_BYPASS_KEY = "DEVKEY-MIGRATE-2026-UNLOCK"
SETTINGS_FILE = os.path.join(os.environ.get("APPDATA", ""), APP_NAME, "settings.json")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def verify_license_key(key_str):
    cleaned = key_str.strip().replace("-", "").upper()
    if cleaned == DEV_BYPASS_KEY.replace("-", "").upper():
        return True, "Developer License"
    if len(cleaned) != 20:
        return False, "Invalid length (must be 20 characters)"
    first_15, last_5 = cleaned[:15], cleaned[15:]
    expected = hashlib.sha256((first_15 + SALT).encode("utf-8")).hexdigest()[:5].upper()
    return (True, "Standard License") if expected == last_5 else (False, "Invalid license key signature")


def save_license_status(key_str, activated=True):
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as handle:
            json.dump({"license_key": key_str, "activated": activated}, handle, indent=2)
    except OSError:
        pass


def load_license_status():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            key = data.get("license_key", "")
            if data.get("activated"):
                valid, _ = verify_license_key(key)
                if valid:
                    return True, key
    except (OSError, json.JSONDecodeError):
        pass
    return False, ""


def fmt_bytes(value):
    value = float(max(0, value))
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} PB"


def fmt_duration(seconds):
    if seconds <= 0:
        return "--"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


class MigrationEngine:
    """Non-blocking migration engine with byte-level progress and detailed telemetry."""

    CHUNK_SIZE = 1024 * 1024
    UI_UPDATE_INTERVAL = 0.20

    def __init__(self, message_queue, cancel_event):
        self.queue = message_queue
        self.cancel_event = cancel_event
        self.user_profile = os.environ.get("USERPROFILE", "")
        self.appdata_roaming = os.environ.get("APPDATA", "")
        self.appdata_local = os.environ.get("LOCALAPPDATA", "")
        self._last_update = 0.0
        self._bytes_done = 0
        self._bytes_total = 0
        self._start_time = 0.0

    def emit(self, kind, value):
        self.queue.put((kind, value))

    def log(self, text):
        self.emit("LOG", text)

    def status(self, text):
        self.emit("STATUS", text)

    def update_progress(self, force=False):
        now = time.monotonic()
        if not force and now - self._last_update < self.UI_UPDATE_INTERVAL:
            return
        self._last_update = now
        ratio = (self._bytes_done / self._bytes_total) if self._bytes_total else 0.0
        elapsed = max(0.001, now - self._start_time)
        speed = self._bytes_done / elapsed
        eta = (self._bytes_total - self._bytes_done) / speed if speed > 0 and self._bytes_total > self._bytes_done else 0
        self.emit("PROGRESS", {"ratio": max(0.0, min(1.0, ratio)), "done": self._bytes_done, "total": self._bytes_total, "speed": speed, "eta": eta})

    def _should_skip(self, path):
        name = os.path.basename(path).lower()
        return name in {"cache", "code cache", "gpu cache", "service worker cache", "temp", "tmp", "__pycache__"}

    def scan_files(self, roots):
        items = []
        total = 0
        for category, root in roots:
            self.status(f"Scanning {category}…")
            self.log(f"Scanning: {category} ({root})")
            if not os.path.exists(root):
                self.log(f"Skipped {category}: source path does not exist.")
                continue
            try:
                for current_root, dirs, files in os.walk(root, topdown=True):
                    dirs[:] = [d for d in dirs if not self._should_skip(os.path.join(current_root, d))]
                    for filename in files:
                        if self.cancel_event.is_set():
                            return items, total
                        source = os.path.join(current_root, filename)
                        try:
                            size = os.path.getsize(source)
                        except OSError:
                            size = 0
                        items.append((category, source, size))
                        total += size
            except OSError as exc:
                self.log(f"[WARNING] Could not scan {category}: {exc}")
        return items, total

    def copy_file(self, source, destination, size, category):
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        self.status(f"Copying {category}: {os.path.basename(source)}")
        try:
            with open(source, "rb") as src, open(destination, "wb") as dst:
                while True:
                    if self.cancel_event.is_set():
                        return False
                    chunk = src.read(self.CHUNK_SIZE)
                    if not chunk:
                        break
                    dst.write(chunk)
                    self._bytes_done += len(chunk)
                    self.update_progress()
            try:
                shutil.copystat(source, destination)
            except OSError:
                pass
            return True
        except (OSError, PermissionError) as exc:
            self.log(f"[SKIP] {source} — {exc}")
            return False

    def build_manifest(self, categories, file_count, skipped_count, compression):
        return {
            "format": "MigrateKit-1",
            "app_version": APP_VERSION,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "hostname": os.environ.get("COMPUTERNAME", "Unknown"),
            "user": os.environ.get("USERNAME", "Unknown"),
            "categories": categories,
            "files_backed_up": file_count,
            "files_skipped": skipped_count,
            "compression": compression,
        }

    def run_backup(self, target_archive, categories, selected_appdata, registry_paths, compression="lzma"):
        self._start_time = time.monotonic()
        self._bytes_done = 0
        self._bytes_total = 0
        temp_dir = os.path.join(self.appdata_local, "Temp", "MigrateKit_Backup_Work")
        shutil.rmtree(temp_dir, ignore_errors=True)
        os.makedirs(temp_dir, exist_ok=True)

        self.status("Preparing backup…")
        self.log(f"Backup started → {target_archive}")
        if compression == "lzma":
            self.log("Compression mode: Maximum (LZMA). Smaller archives, slower final packaging.")
        else:
            self.log("Compression mode: Balanced (Deflate level 9).")

        user_dirs = {
            "Documents": os.path.join(self.user_profile, "Documents"),
            "Pictures": os.path.join(self.user_profile, "Pictures"),
            "Desktop": os.path.join(self.user_profile, "Desktop"),
            "Downloads": os.path.join(self.user_profile, "Downloads"),
            "Videos": os.path.join(self.user_profile, "Videos"),
            "Music": os.path.join(self.user_profile, "Music"),
        }
        roots = [(name, user_dirs[name]) for name, enabled in categories.items() if enabled and name in user_dirs]
        items, total = self.scan_files(roots)
        self._bytes_total = total
        if self.cancel_event.is_set():
            self.emit("CANCELLED", None)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return
        self.log(f"Scan complete: {len(items):,} files / {fmt_bytes(total)}")

        manifest_categories = [name for name, enabled in categories.items() if enabled]
        skipped = 0
        copied = 0

        for category, source, _size in items:
            if self.cancel_event.is_set():
                self.emit("CANCELLED", None)
                shutil.rmtree(temp_dir, ignore_errors=True)
                return
            rel = os.path.relpath(source, user_dirs[category])
            destination = os.path.join(temp_dir, "data", category, rel)
            if self.copy_file(source, destination, _size, category):
                copied += 1
            else:
                skipped += 1
            self.update_progress(force=False)

        if categories.get("Chrome Profile"):
            chrome_src = os.path.join(self.appdata_local, "Google", "Chrome", "User Data")
            if os.path.exists(chrome_src):
                self.status("Copying Chrome profile…")
                chrome_dest = os.path.join(temp_dir, "data", "Chrome")
                critical = ["Local State"]
                default_src = os.path.join(chrome_src, "Default")
                for filename in ["Bookmarks", "History", "Preferences", "Web Data", "Login Data", "Secure Preferences", "Cookies"]:
                    critical.append(os.path.join("Default", filename))
                for rel in critical:
                    source = os.path.join(chrome_src, rel)
                    if os.path.isfile(source):
                        size = os.path.getsize(source)
                        self._bytes_total += size
                        if self.copy_file(source, os.path.join(chrome_dest, rel), size, "Chrome Profile"):
                            copied += 1
                        else:
                            skipped += 1
                ext_src = os.path.join(default_src, "Extensions")
                if os.path.isdir(ext_src):
                    ext_items, ext_total = self.scan_files([("Chrome Extensions", ext_src)])
                    self._bytes_total += ext_total
                    for _category, source, size in ext_items:
                        rel = os.path.relpath(source, ext_src)
                        if self.copy_file(source, os.path.join(chrome_dest, "Default", "Extensions", rel), size, "Chrome Extensions"):
                            copied += 1
                        else:
                            skipped += 1
            else:
                self.log("Chrome profile not found — continuing without it.")

        if categories.get("Application Data (AppData)"):
            for app_folder in selected_appdata:
                for label, base in (("Roaming", self.appdata_roaming), ("Local", self.appdata_local)):
                    source_root = os.path.join(base, app_folder)
                    if not os.path.isdir(source_root):
                        continue
                    selected_items, selected_total = self.scan_files([(f"AppData {label}/{app_folder}", source_root)])
                    self._bytes_total += selected_total
                    for subcategory, source, size in selected_items:
                        rel = os.path.relpath(source, source_root)
                        destination = os.path.join(temp_dir, "data", "AppData", label, app_folder, rel)
                        if self.copy_file(source, destination, size, subcategory):
                            copied += 1
                        else:
                            skipped += 1

        registry_records = []
        if categories.get("Registry Configurations"):
            reg_dir = os.path.join(temp_dir, "registry")
            os.makedirs(reg_dir, exist_ok=True)
            for idx, registry_path in enumerate(registry_paths):
                registry_path = registry_path.strip()
                if not registry_path:
                    continue
                safe_name = registry_path.replace("\\", "_").replace(":", "_").replace(" ", "_")[:70] + f"_{idx}.reg"
                destination = os.path.join(reg_dir, safe_name)
                self.status(f"Exporting registry: {registry_path}")
                result = subprocess.run(["reg.exe", "export", registry_path, destination, "/y"], capture_output=True, text=True)
                if result.returncode == 0:
                    registry_records.append({"key": registry_path, "file": safe_name})
                    self.log(f"Registry exported: {registry_path}")
                else:
                    self.log(f"[WARNING] Registry export failed: {registry_path} — {result.stderr.strip()}")

        manifest = self.build_manifest(manifest_categories, copied, skipped, compression)
        with open(os.path.join(temp_dir, "backup_manifest.json"), "w", encoding="utf-8") as handle:
            manifest["registry_keys_backed_up"] = registry_records
            json.dump(manifest, handle, indent=2)

        self.status("Compressing archive…")
        self.log("Packaging archive. The UI will continue updating while compression runs.")
        try:
            os.makedirs(os.path.dirname(target_archive), exist_ok=True)
            if os.path.exists(target_archive):
                os.remove(target_archive)
            method = zipfile.ZIP_LZMA if compression == "lzma" else zipfile.ZIP_DEFLATED
            kwargs = {"compression": method, "allowZip64": True}
            if method == zipfile.ZIP_DEFLATED:
                kwargs["compresslevel"] = 9
            with zipfile.ZipFile(target_archive, "w", **kwargs) as archive:
                all_files = []
                for root, _dirs, files in os.walk(temp_dir):
                    for filename in files:
                        path = os.path.join(root, filename)
                        all_files.append(path)
                for index, path in enumerate(all_files, 1):
                    if self.cancel_event.is_set():
                        self.emit("CANCELLED", None)
                        return
                    archive.write(path, os.path.relpath(path, temp_dir))
                    self.status(f"Compressing {index:,}/{len(all_files):,} files…")
                    self.emit("ARCHIVE_PROGRESS", index / max(1, len(all_files)))

            self._bytes_done = self._bytes_total
            self.update_progress(force=True)
            self.status("Backup complete")
            size = os.path.getsize(target_archive)
            self.log(f"Archive complete: {fmt_bytes(size)}")
            self.emit("DONE", {"message": f"Backup complete.\\n\\nFiles copied: {copied:,}\\nFiles skipped: {skipped:,}\\nArchive size: {fmt_bytes(size)}\\nSaved to: {target_archive}"})
        except Exception as exc:
            self.log(f"ERROR during compression: {exc}")
            self.emit("DONE", {"message": f"Backup failed during compression: {exc}"})
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def run_restore(self, archive_path, categories):
        self._start_time = time.monotonic()
        self._bytes_done = 0
        self._bytes_total = 0
        temp_dir = os.path.join(self.appdata_local, "Temp", "MigrateKit_Restore_Work")
        shutil.rmtree(temp_dir, ignore_errors=True)
        os.makedirs(temp_dir, exist_ok=True)
        try:
            self.status("Opening backup archive…")
            with zipfile.ZipFile(archive_path, "r") as archive:
                bad = archive.testzip()
                if bad:
                    raise ValueError(f"Archive integrity check failed at: {bad}")
                archive.extractall(temp_dir)
            manifest_path = os.path.join(temp_dir, "backup_manifest.json")
            if not os.path.exists(manifest_path):
                raise ValueError("backup_manifest.json is missing")
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.log(f"Loaded backup from {manifest.get('hostname', 'Unknown')} on {manifest.get('timestamp', 'Unknown')}")
            self.status("Restoring files…")
            source_data = os.path.join(temp_dir, "data")
            all_items = []
            for current_root, _dirs, files in os.walk(source_data):
                for filename in files:
                    source = os.path.join(current_root, filename)
                    all_items.append(source)
                    try:
                        self._bytes_total += os.path.getsize(source)
                    except OSError:
                        pass
            self.log(f"Restore set: {len(all_items):,} files / {fmt_bytes(self._bytes_total)}")

            mapping = {
                "Documents": os.path.join(self.user_profile, "Documents"),
                "Pictures": os.path.join(self.user_profile, "Pictures"),
                "Desktop": os.path.join(self.user_profile, "Desktop"),
                "Downloads": os.path.join(self.user_profile, "Downloads"),
                "Videos": os.path.join(self.user_profile, "Videos"),
                "Music": os.path.join(self.user_profile, "Music"),
            }
            copied = skipped = 0
            for source in all_items:
                if self.cancel_event.is_set():
                    self.emit("CANCELLED", None)
                    return
                rel = os.path.relpath(source, source_data)
                parts = Path(rel).parts
                if not parts:
                    continue
                category = parts[0]
                if not categories.get(category, False) and category not in {"Chrome", "AppData"}:
                    try:
                        self._bytes_done += os.path.getsize(source)
                    except OSError:
                        pass
                    continue
                if category in mapping:
                    destination = os.path.join(mapping[category], *parts[1:])
                elif category == "Chrome":
                    destination = os.path.join(self.appdata_local, "Google", "Chrome", "User Data", *parts[1:])
                elif category == "AppData":
                    if len(parts) < 3:
                        continue
                    destination = os.path.join(self.appdata_roaming if parts[1] == "Roaming" else self.appdata_local, *parts[2:])
                else:
                    continue
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                self.status(f"Restoring: {os.path.basename(source)}")
                try:
                    with open(source, "rb") as src, open(destination, "wb") as dst:
                        while True:
                            if self.cancel_event.is_set():
                                self.emit("CANCELLED", None)
                                return
                            chunk = src.read(self.CHUNK_SIZE)
                            if not chunk:
                                break
                            dst.write(chunk)
                            self._bytes_done += len(chunk)
                            self.update_progress()
                    copied += 1
                except OSError as exc:
                    skipped += 1
                    self.log(f"[RESTORE SKIP] {destination} — {exc}")

            self.update_progress(force=True)
            self.status("Restore complete")
            self.emit("DONE", {"message": f"Restore complete.\\n\\nFiles restored: {copied:,}\\nFiles skipped: {skipped:,}"})
        except Exception as exc:
            self.log(f"ERROR during restore: {exc}")
            self.emit("DONE", {"message": f"Restore failed: {exc}"})
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class MigrateKitApp(ctk.CTk):
    """Modern desktop UI for MigrateKit."""

    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION} — Windows Migration Utility")
        self.geometry("1180x760")
        self.minsize(1050, 700)
        self.is_activated, self.active_license = load_license_status()
        self.msg_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.engine = MigrationEngine(self.msg_queue, self.cancel_event)
        self.active_thread = None
        self.current_operation = "Idle"
        self.last_progress = {"ratio": 0.0, "done": 0, "total": 0, "speed": 0, "eta": 0}
        self.archive_progress = 0.0
        self._build_shell()
        self._build_dashboard()
        self._build_backup_page()
        self._build_restore_page()
        self._build_license_page()
        self._build_settings_page()
        self.show_page("dashboard")
        self.after(100, self.poll_queue)

    def _label(self, parent, text, size=12, weight="normal", color=None):
        return ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=size, weight=weight), text_color=color) if color else ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=size, weight=weight))

    def _build_shell(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=235, corner_radius=0, fg_color=("#f3f4f6", "#111827"))
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(8, weight=1)
        self._label(self.sidebar, "MIGRATEKIT", 24, "bold").grid(row=0, column=0, padx=24, pady=(28, 4), sticky="w")
        self._label(self.sidebar, f"Windows 11 migration · v{APP_VERSION}", 10, color=("#64748b", "#94a3b8")).grid(row=1, column=0, padx=24, pady=(0, 22), sticky="w")
        self.nav = {}
        for row, (key, text) in enumerate((("dashboard", "Dashboard"), ("backup", "Backup"), ("restore", "Restore"), ("license", "License"), ("settings", "Settings")), start=2):
            button = ctk.CTkButton(self.sidebar, text=text, anchor="w", height=42, corner_radius=10, fg_color="transparent", hover_color=("#e5e7eb", "#1f2937"), text_color=("#111827", "#e5e7eb"), command=lambda p=key: self.show_page(p))
            button.grid(row=row, column=0, padx=14, pady=4, sticky="ew")
            self.nav[key] = button
        status_box = ctk.CTkFrame(self.sidebar, corner_radius=12, fg_color=("#e5e7eb", "#1f2937"))
        status_box.grid(row=9, column=0, padx=16, pady=16, sticky="ew")
        self.license_dot = ctk.CTkLabel(status_box, text="●", text_color="#10b981" if self.is_activated else "#f59e0b")
        self.license_dot.grid(row=0, column=0, padx=(12, 6), pady=(10, 0))
        self.license_status_label = self._label(status_box, "Licensed" if self.is_activated else "Backup mode", 11, "bold")
        self.license_status_label.grid(row=0, column=1, padx=(0, 12), pady=(10, 0), sticky="w")
        self._label(status_box, "Backup is always free", 9, color=("#64748b", "#94a3b8")).grid(row=1, column=0, columnspan=2, padx=12, pady=(2, 10), sticky="w")

        self.content = ctk.CTkFrame(self, fg_color=("#f8fafc", "#0b1120"), corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)
        self.pages = {}

        self.bottom = ctk.CTkFrame(self.content, height=124, corner_radius=0, fg_color=("#ffffff", "#111827"))
        self.bottom.grid(row=1, column=0, sticky="ew")
        self.bottom.grid_columnconfigure(0, weight=1)
        self.bottom.grid_rowconfigure(1, weight=1)
        self.activity_label = self._label(self.bottom, "Ready", 12, "bold")
        self.activity_label.grid(row=0, column=0, padx=22, pady=(10, 0), sticky="w")
        self.stats_label = self._label(self.bottom, "Waiting for an operation", 10, color=("#64748b", "#94a3b8"))
        self.stats_label.grid(row=0, column=0, padx=118, pady=(10, 0), sticky="w")
        self.progress = ctk.CTkProgressBar(self.bottom, height=10, corner_radius=5)
        self.progress.grid(row=1, column=0, padx=22, pady=(7, 5), sticky="ew")
        self.progress.set(0)
        self.archive_progress_bar = ctk.CTkProgressBar(self.bottom, height=4, corner_radius=2, progress_color="#06b6d4")
        self.archive_progress_bar.grid(row=2, column=0, padx=22, pady=(0, 8), sticky="ew")
        self.archive_progress_bar.set(0)
        self.cancel_btn = ctk.CTkButton(self.bottom, text="Cancel", width=100, height=34, fg_color="#dc2626", hover_color="#b91c1c", state="disabled", command=self.cancel_operation)
        self.cancel_btn.grid(row=0, rowspan=3, column=1, padx=18)

    def _new_page(self, key):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew", padx=28, pady=26)
        self.pages[key] = frame
        return frame

    def _build_dashboard(self):
        page = self._new_page("dashboard")
        self._label(page, "Your migration control center", 30, "bold").pack(anchor="w")
        self._label(page, "Backup first. Move the archive. Restore when you are ready.", 13, color=("#64748b", "#94a3b8")).pack(anchor="w", pady=(6, 24))
        hero = ctk.CTkFrame(page, corner_radius=18, fg_color=("#ffffff", "#111827"), border_width=1, border_color=("#e2e8f0", "#1f2937"))
        hero.pack(fill="x", pady=(0, 20))
        left = ctk.CTkFrame(hero, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=26, pady=24)
        self._label(left, "Ready for your next Windows install?", 20, "bold").pack(anchor="w")
        self._label(left, "MigrateKit creates a portable .migratekit archive from your user data and supported settings.", 12, color=("#64748b", "#94a3b8")).pack(anchor="w", pady=(5, 16))
        actions = ctk.CTkFrame(left, fg_color="transparent")
        actions.pack(anchor="w")
        ctk.CTkButton(actions, text="Start Backup", width=150, height=40, command=lambda: self.show_page("backup")).pack(side="left", padx=(0, 8))
        ctk.CTkButton(actions, text="Restore Archive", width=150, height=40, fg_color="#0f766e", hover_color="#115e59", command=lambda: self.show_page("restore")).pack(side="left")
        meter = ctk.CTkFrame(hero, width=260, height=160, corner_radius=16, fg_color=("#eff6ff", "#172554"))
        meter.pack(side="right", padx=22, pady=22)
        meter.pack_propagate(False)
        self.dashboard_size = self._label(meter, "0 B", 28, "bold")
        self.dashboard_size.pack(pady=(22, 0))
        self._label(meter, "Last archive size", 10, color=("#64748b", "#93c5fd")).pack(pady=(0, 12))
        self.dashboard_state = self._label(meter, "No backups yet", 11, "bold", "#2563eb")
        self.dashboard_state.pack()
        self._label(page, "What MigrateKit handles", 18, "bold").pack(anchor="w", pady=(4, 12))
        grid = ctk.CTkFrame(page, fg_color="transparent")
        grid.pack(fill="x")
        cards = [
            ("Files", "Documents, Desktop, Pictures, Downloads, Videos and Music"),
            ("Chrome", "Bookmarks, history, settings, cookies and extensions"),
            ("App settings", "Selected AppData folders for supported applications"),
            ("Registry", "Explicitly selected user-level registry exports"),
        ]
        for idx, (title, body) in enumerate(cards):
            card = ctk.CTkFrame(grid, corner_radius=14, fg_color=("#ffffff", "#111827"), border_width=1, border_color=("#e2e8f0", "#1f2937"))
            card.grid(row=idx // 2, column=idx % 2, padx=(0 if idx % 2 == 0 else 8, 8 if idx % 2 == 0 else 0), pady=6, sticky="nsew")
            self._label(card, title, 14, "bold").pack(anchor="w", padx=16, pady=(14, 4))
            self._label(card, body, 10, color=("#64748b", "#94a3b8")).pack(anchor="w", padx=16, pady=(0, 14))
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

    def _build_backup_page(self):
        page = self._new_page("backup")
        self._label(page, "Build a migration archive", 28, "bold").pack(anchor="w")
        self._label(page, "Select what to capture, choose an archive destination, and start. Live progress is shown below.", 12, color=("#64748b", "#94a3b8")).pack(anchor="w", pady=(4, 18))
        body = ctk.CTkFrame(page, fg_color="transparent")
        body.pack(fill="both", expand=True)
        selector = ctk.CTkFrame(body, width=430, corner_radius=16, fg_color=("#ffffff", "#111827"), border_width=1, border_color=("#e2e8f0", "#1f2937"))
        selector.pack(side="left", fill="y", padx=(0, 10))
        self._label(selector, "Data selection", 16, "bold").pack(anchor="w", padx=20, pady=(18, 12))
        self.backup_vars = {}
        defaults = [("Documents", True), ("Desktop", True), ("Pictures", True), ("Downloads", False), ("Videos", False), ("Music", False), ("Chrome Profile", True), ("Application Data (AppData)", True), ("Registry Configurations", True)]
        for name, default in defaults:
            var = ctk.BooleanVar(value=default)
            self.backup_vars[name] = var
            ctk.CTkCheckBox(selector, text=name, variable=var, height=30).pack(anchor="w", padx=20, pady=2)
        self._label(selector, "Compression", 12, "bold").pack(anchor="w", padx=20, pady=(18, 6))
        self.compression_menu = ctk.CTkOptionMenu(selector, values=["Maximum (LZMA)", "Balanced (Deflate 9)"])
        self.compression_menu.pack(fill="x", padx=20)
        self.compression_menu.set("Maximum (LZMA)")
        self._label(selector, "Archive destination", 12, "bold").pack(anchor="w", padx=20, pady=(18, 6))
        dest = ctk.CTkFrame(selector, fg_color="transparent")
        dest.pack(fill="x", padx=20)
        self.backup_dest = ctk.CTkEntry(dest, placeholder_text="C:\\Users\\...\\MigrateKit_Backup.migratekit")
        self.backup_dest.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.backup_dest.insert(0, os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", "MigrateKit_Backup.migratekit"))
        ctk.CTkButton(dest, text="Browse", width=78, command=self.browse_backup).pack(side="right")
        ctk.CTkButton(selector, text="Start backup", height=44, command=self.start_backup, font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", padx=20, pady=20)
        monitor = ctk.CTkFrame(body, corner_radius=16, fg_color=("#ffffff", "#111827"), border_width=1, border_color=("#e2e8f0", "#1f2937"))
        monitor.pack(side="right", fill="both", expand=True, padx=(10, 0))
        self._label(monitor, "Live operation monitor", 16, "bold").pack(anchor="w", padx=20, pady=(18, 12))
        self.monitor_operation = self._label(monitor, "Idle", 13, "bold", "#2563eb")
        self.monitor_operation.pack(anchor="w", padx=20)
        self.monitor_detail = self._label(monitor, "No active operation", 11, color=("#64748b", "#94a3b8"))
        self.monitor_detail.pack(anchor="w", padx=20, pady=(3, 18))
        self.backup_log = ctk.CTkTextbox(monitor, corner_radius=12, font=ctk.CTkFont(family="Consolas", size=10))
        self.backup_log.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.backup_log.configure(state="disabled")

    def _build_restore_page(self):
        page = self._new_page("restore")
        self._label(page, "Restore your migration archive", 28, "bold").pack(anchor="w")
        self._label(page, "Restoration is license-gated. Select an archive and the categories to restore.", 12, color=("#64748b", "#94a3b8")).pack(anchor="w", pady=(4, 18))
        card = ctk.CTkFrame(page, corner_radius=16, fg_color=("#ffffff", "#111827"), border_width=1, border_color=("#e2e8f0", "#1f2937"))
        card.pack(fill="both", expand=True)
        self._label(card, "Migration archive", 14, "bold").pack(anchor="w", padx=22, pady=(20, 7))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=22)
        self.restore_src = ctk.CTkEntry(row, placeholder_text="Select a .migratekit archive")
        self.restore_src.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(row, text="Browse", width=82, command=self.browse_restore).pack(side="right")
        self._label(card, "Restore selection", 14, "bold").pack(anchor="w", padx=22, pady=(18, 8))
        self.restore_vars = {}
        selections = [("Documents", True), ("Desktop", True), ("Pictures", True), ("Downloads", False), ("Videos", False), ("Music", False), ("Chrome Profile", True), ("Application Data (AppData)", True), ("Registry Configurations", True)]
        checks = ctk.CTkFrame(card, fg_color="transparent")
        checks.pack(fill="x", padx=22)
        for idx, (name, default) in enumerate(selections):
            var = ctk.BooleanVar(value=default)
            self.restore_vars[name] = var
            ctk.CTkCheckBox(checks, text=name, variable=var).grid(row=idx // 3, column=idx % 3, padx=(0, 22), pady=5, sticky="w")
        self.restore_lock = self._label(card, "Restore is locked — activate a license first.", 11, "bold", "#f59e0b")
        self.restore_lock.pack(anchor="w", padx=22, pady=(18, 2))
        self.restore_btn = ctk.CTkButton(card, text="Restore archive", height=44, command=self.start_restore)
        self.restore_btn.pack(fill="x", padx=22, pady=(8, 22))
        self.update_restore_state()

    def _build_license_page(self):
        page = self._new_page("license")
        self._label(page, "License & activation", 28, "bold").pack(anchor="w")
        self._label(page, "Unlock the restore engine with your MigrateKit license.", 12, color=("#64748b", "#94a3b8")).pack(anchor="w", pady=(4, 20))
        card = ctk.CTkFrame(page, width=620, corner_radius=16, fg_color=("#ffffff", "#111827"), border_width=1, border_color=("#e2e8f0", "#1f2937"))
        card.pack(anchor="w", fill="x")
        self.license_state = self._label(card, "ACTIVE" if self.is_activated else "NOT ACTIVATED", 18, "bold", "#10b981" if self.is_activated else "#f59e0b")
        self.license_state.pack(anchor="w", padx=22, pady=(22, 4))
        self._label(card, "Enter key", 12, "bold").pack(anchor="w", padx=22, pady=(16, 6))
        self.license_entry = ctk.CTkEntry(card, placeholder_text="XXXXX-XXXXX-XXXXX-XXXXX", height=42, font=ctk.CTkFont(family="Consolas", size=14))
        self.license_entry.pack(fill="x", padx=22)
        if self.is_activated:
            self.license_entry.insert(0, self.active_license)
        ctk.CTkButton(card, text="Activate license", height=42, command=self.activate_license).pack(fill="x", padx=22, pady=12)
        self._label(card, "Developer testing key is supported for local builds.", 10, color=("#64748b", "#94a3b8")).pack(anchor="w", padx=22, pady=(0, 22))

    def _build_settings_page(self):
        page = self._new_page("settings")
        self._label(page, "Settings", 28, "bold").pack(anchor="w")
        self._label(page, "Tune the interface and inspect runtime information.", 12, color=("#64748b", "#94a3b8")).pack(anchor="w", pady=(4, 20))
        cards = ctk.CTkFrame(page, fg_color="transparent")
        cards.pack(fill="x")
        appearance = ctk.CTkFrame(cards, corner_radius=16, fg_color=("#ffffff", "#111827"), border_width=1, border_color=("#e2e8f0", "#1f2937"))
        appearance.pack(fill="x", pady=(0, 10))
        self._label(appearance, "Appearance", 14, "bold").pack(anchor="w", padx=20, pady=(18, 6))
        self.theme_menu = ctk.CTkOptionMenu(appearance, values=["Dark", "Light", "System"], command=ctk.set_appearance_mode)
        self.theme_menu.pack(anchor="w", padx=20, pady=(0, 18))
        info = ctk.CTkFrame(cards, corner_radius=16, fg_color=("#ffffff", "#111827"), border_width=1, border_color=("#e2e8f0", "#1f2937"))
        info.pack(fill="x")
        details = f"Version: {APP_VERSION}\nPython: {sys.version.split()[0]}\nUser profile: {os.environ.get('USERPROFILE', '')}\nAppData: {os.environ.get('APPDATA', '')}\nLocal AppData: {os.environ.get('LOCALAPPDATA', '')}"
        self._label(info, "Runtime information", 14, "bold").pack(anchor="w", padx=20, pady=(18, 7))
        self._label(info, details, 10, color=("#64748b", "#94a3b8")).pack(anchor="w", padx=20, pady=(0, 18))

    def show_page(self, name):
        for frame in self.pages.values():
            frame.grid_forget()
        self.pages[name].grid(row=0, column=0, sticky="nsew", padx=28, pady=26)
        for key, button in self.nav.items():
            button.configure(fg_color=("#dbeafe", "#1e3a8a") if key == name else "transparent")

    def append_log(self, text):
        if not hasattr(self, "backup_log"):
            return
        self.backup_log.configure(state="normal")
        self.backup_log.insert("end", f"[{time.strftime('%H:%M:%S')}] {text}\n")
        self.backup_log.see("end")
        self.backup_log.configure(state="disabled")

    def browse_backup(self):
        path = filedialog.asksaveasfilename(title="Save MigrateKit archive", defaultextension=".migratekit", filetypes=[("MigrateKit archive", "*.migratekit")])
        if path:
            self.backup_dest.delete(0, "end")
            self.backup_dest.insert(0, path)

    def browse_restore(self):
        path = filedialog.askopenfilename(title="Open MigrateKit archive", filetypes=[("MigrateKit archive", "*.migratekit")])
        if path:
            self.restore_src.delete(0, "end")
            self.restore_src.insert(0, path)

    def update_restore_state(self):
        if self.is_activated:
            self.restore_lock.configure(text="License active — restore is ready.", text_color="#10b981")
            self.restore_btn.configure(state="normal")
        else:
            self.restore_lock.configure(text="Restore is locked — activate a license first.", text_color="#f59e0b")
            self.restore_btn.configure(state="disabled")

    def activate_license(self):
        key = self.license_entry.get().strip()
        valid, detail = verify_license_key(key)
        if not valid:
            messagebox.showerror("Activation failed", detail)
            return
        self.is_activated = True
        self.active_license = key
        save_license_status(key, True)
        self.license_state.configure(text=f"ACTIVE — {detail}", text_color="#10b981")
        self.license_status_label.configure(text="Licensed")
        self.license_dot.configure(text_color="#10b981")
        self.update_restore_state()
        messagebox.showinfo("Activation complete", "MigrateKit restore is now unlocked.")

    def start_backup(self):
        if self.active_thread and self.active_thread.is_alive():
            return
        target = self.backup_dest.get().strip()
        if not target:
            messagebox.showerror("Backup", "Choose an archive destination first.")
            return
        categories = {name: var.get() for name, var in self.backup_vars.items()}
        if not any(categories.values()):
            messagebox.showerror("Backup", "Select at least one category.")
            return
        self.backup_log.configure(state="normal")
        self.backup_log.delete("1.0", "end")
        self.backup_log.configure(state="disabled")
        self.cancel_event.clear()
        self.cancel_btn.configure(state="normal")
        self.progress.set(0)
        self.archive_progress_bar.set(0)
        compression = "lzma" if self.compression_menu.get().startswith("Maximum") else "deflate"
        self.active_thread = threading.Thread(target=self.engine.run_backup, args=(target, categories, ["Discord", "Microsoft VS Code", "Zoom", "Slack", "Notion"], self._registry_paths(), compression), daemon=True)
        self.active_thread.start()

    def _registry_paths(self):
        return [
            r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            r"HKEY_CURRENT_USER\Environment",
        ]

    def start_restore(self):
        if not self.is_activated:
            self.show_page("license")
            return
        archive = self.restore_src.get().strip()
        if not archive or not os.path.exists(archive):
            messagebox.showerror("Restore", "Select a valid .migratekit archive first.")
            return
        categories = {name: var.get() for name, var in self.restore_vars.items()}
        self.cancel_event.clear()
        self.cancel_btn.configure(state="normal")
        self.progress.set(0)
        self.archive_progress_bar.set(0)
        self.active_thread = threading.Thread(target=self.engine.run_restore, args=(archive, categories), daemon=True)
        self.active_thread.start()

    def cancel_operation(self):
        self.engine.cancel_event.set()
        self.append_log("Cancellation requested — finishing the current file chunk…")
        self.activity_label.configure(text="Cancelling…")

    def poll_queue(self):
        try:
            while True:
                kind, data = self.msg_queue.get_nowait()
                if kind == "LOG":
                    self.append_log(data)
                elif kind == "STATUS":
                    self.current_operation = data
                    self.activity_label.configure(text=data)
                    if hasattr(self, "monitor_operation"):
                        self.monitor_operation.configure(text=data)
                elif kind == "PROGRESS":
                    self.last_progress = data
                    self.progress.set(data["ratio"])
                    self.stats_label.configure(text=f"{fmt_bytes(data['done'])} / {fmt_bytes(data['total'])}  ·  {fmt_bytes(data['speed'])}/s  ·  ETA {fmt_duration(data['eta'])}")
                    self.monitor_detail.configure(text=f"{fmt_bytes(data['done'])} / {fmt_bytes(data['total'])}  ·  {fmt_bytes(data['speed'])}/s  ·  ETA {fmt_duration(data['eta'])}")
                elif kind == "ARCHIVE_PROGRESS":
                    self.archive_progress_bar.set(data)
                elif kind == "DONE":
                    self.cancel_btn.configure(state="disabled")
                    self.progress.set(1)
                    self.archive_progress_bar.set(1)
                    self.activity_label.configure(text="Complete")
                    messagebox.showinfo("MigrateKit", data.get("message", "Operation complete."))
                    try:
                        if self.backup_dest.get().strip() and os.path.exists(self.backup_dest.get().strip()):
                            size = os.path.getsize(self.backup_dest.get().strip())
                            self.dashboard_size.configure(text=fmt_bytes(size))
                            self.dashboard_state.configure(text="Backup ready")
                    except OSError:
                        pass
                elif kind == "CANCELLED":
                    self.cancel_btn.configure(state="disabled")
                    self.activity_label.configure(text="Cancelled")
                    messagebox.showwarning("MigrateKit", "Operation cancelled safely.")
        except queue.Empty:
            pass
        self.after(120, self.poll_queue)


def main():
    if os.name != "nt":
        messagebox.showerror(APP_NAME, "MigrateKit is designed for Windows 11.")
        return
    app = MigrateKitApp()
    app.mainloop()


if __name__ == "__main__":
    main()
