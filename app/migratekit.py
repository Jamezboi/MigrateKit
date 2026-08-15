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
import winreg
import customtkinter as ctk
from tkinter import filedialog, messagebox

# Set appearance and theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Constants
SALT = "MIGRATEKIT-SALT-2026"
DEV_BYPASS_KEY = "DEVKEY-MIGRATE-2026-UNLOCK"
SETTINGS_FILE = os.path.join(os.environ.get("APPDATA", ""), "MigrateKit", "settings.json")

def verify_license_key(key_str):
    """Verifies the license key using SHA-256 and salt, or the developer bypass key."""
    cleaned = key_str.strip().replace("-", "").upper()
    if cleaned == DEV_BYPASS_KEY.replace("-", "").upper():
        return True, "Developer License"
    
    if len(cleaned) != 20:
        return False, "Invalid length (must be 20 characters)"
        
    first_15 = cleaned[:15]
    last_5 = cleaned[15:]
    
    # Calculate checksum hash
    hasher = hashlib.sha256()
    hasher.update((first_15 + SALT).encode('utf-8'))
    expected_hash = hasher.hexdigest().upper()
    
    if expected_hash[:5] == last_5:
        return True, "Standard License"
    return False, "Invalid license key signature"

def save_license_status(key_str, activated=True):
    """Saves the license key to AppData to persist activation state."""
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"license_key": key_str, "activated": activated}, f)
    except Exception as e:
        print(f"Error saving settings: {e}")

def load_license_status():
    """Loads the license key from AppData and validates it."""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
                key = data.get("license_key", "")
                activated = data.get("activated", False)
                if activated:
                    valid, _ = verify_license_key(key)
                    if valid:
                        return True, key
    except Exception as e:
        print(f"Error loading settings: {e}")
    return False, ""

class MigrationEngine:
    """Core class for performing backup and restore operations in a background thread."""
    def __init__(self, msg_queue, cancel_event):
        self.queue = msg_queue
        self.cancel_event = cancel_event
        self.user_profile = os.environ.get("USERPROFILE", "")
        self.appdata_roaming = os.environ.get("APPDATA", "")
        self.appdata_local = os.environ.get("LOCALAPPDATA", "")
        
    def log(self, message):
        self.queue.put(("LOG", message))
        
    def set_progress(self, val):
        self.queue.put(("PROGRESS", val))

    def run_backup(self, target_zip_path, categories, selected_appdata, registry_paths):
        """Runs the backup process."""
        self.set_progress(0.0)
        temp_dir = os.path.join(self.appdata_local, "Temp", "MigrateKit_Temp_Backup")
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
        os.makedirs(temp_dir, exist_ok=True)
        
        self.log(f"Starting backup process. Temporary directory created at: {temp_dir}")
        
        # Manifest dictionary
        manifest = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "hostname": os.environ.get("COMPUTERNAME", "Unknown"),
            "user": os.environ.get("USERNAME", "Unknown"),
            "categories": [],
            "files_backed_up": 0,
            "registry_keys_backed_up": []
        }
        
        # Map categories to actual paths
        user_dirs = {
            "Documents": os.path.join(self.user_profile, "Documents"),
            "Pictures": os.path.join(self.user_profile, "Pictures"),
            "Desktop": os.path.join(self.user_profile, "Desktop"),
            "Downloads": os.path.join(self.user_profile, "Downloads"),
            "Videos": os.path.join(self.user_profile, "Videos"),
            "Music": os.path.join(self.user_profile, "Music")
        }
        
        total_steps = len([c for c in categories.values() if c])
        if total_steps == 0:
            self.log("ERROR: No categories selected for backup.")
            self.queue.put(("DONE", "Error: No categories selected"))
            return
            
        current_step = 0
        
        for cat_name, is_selected in categories.items():
            if self.cancel_event.is_set():
                self.log("Backup cancelled by user.")
                self.queue.put(("CANCELLED", None))
                return
                
            if not is_selected:
                continue
                
            current_step += 1
            self.log(f"[{current_step}/{total_steps}] Backing up {cat_name}...")
            self.set_progress(current_step / (total_steps + 1))
            
            # 1. Standard user directories
            if cat_name in user_dirs:
                src_path = user_dirs[cat_name]
                dest_path = os.path.join(temp_dir, "data", cat_name)
                if os.path.exists(src_path):
                    self.copy_folder_with_logging(src_path, dest_path, manifest)
                else:
                    self.log(f"Skipping {cat_name}: path does not exist.")
            
            # 2. Chrome profile
            elif cat_name == "Chrome Profile":
                chrome_src = os.path.join(self.appdata_local, "Google", "Chrome", "User Data")
                chrome_dest = os.path.join(temp_dir, "data", "Chrome")
                
                # Check if Chrome is running
                tasklist = subprocess.run("tasklist /FI \"IMAGENAME eq chrome.exe\"", shell=True, capture_output=True, text=True)
                if "chrome.exe" in tasklist.stdout:
                    self.log("[WARNING] Google Chrome is currently running. Some profile files might be locked. Close Chrome for best results.")
                
                if os.path.exists(chrome_src):
                    # We back up critical profile elements rather than the huge Cache
                    os.makedirs(chrome_dest, exist_ok=True)
                    
                    # Copy Local State
                    local_state = os.path.join(chrome_src, "Local State")
                    if os.path.exists(local_state):
                        shutil.copy2(local_state, os.path.join(chrome_dest, "Local State"))
                        manifest["files_backed_up"] += 1
                        
                    # Copy Default folder contents (Bookmarks, History, Preferences, Web Data, Login Data, Secure Preferences)
                    default_src = os.path.join(chrome_src, "Default")
                    default_dest = os.path.join(chrome_dest, "Default")
                    
                    if os.path.exists(default_src):
                        os.makedirs(default_dest, exist_ok=True)
                        critical_files = [
                            "Bookmarks", "History", "Preferences", "Web Data", 
                            "Login Data", "Secure Preferences", "Cookies"
                        ]
                        for f in critical_files:
                            file_src_path = os.path.join(default_src, f)
                            if os.path.exists(file_src_path):
                                try:
                                    shutil.copy2(file_src_path, os.path.join(default_dest, f))
                                    manifest["files_backed_up"] += 1
                                except Exception as e:
                                    self.log(f"Could not backup Chrome file '{f}' (locked/in-use): {e}")
                                    
                        # Copy Extensions (optional but good)
                        ext_src = os.path.join(default_src, "Extensions")
                        if os.path.exists(ext_src):
                            self.copy_folder_with_logging(ext_src, os.path.join(default_dest, "Extensions"), manifest)
                            
                        self.log("Chrome profile data successfully packaged.")
                    else:
                        self.log("Chrome 'Default' profile directory not found.")
                else:
                    self.log("Google Chrome profile installation folder not found.")
                    
            # 3. AppData (Selective)
            elif cat_name == "Application Data (AppData)":
                appdata_dest = os.path.join(temp_dir, "data", "AppData")
                for app_folder in selected_appdata:
                    if self.cancel_event.is_set():
                        self.queue.put(("CANCELLED", None))
                        return
                    app_src_path = os.path.join(self.appdata_roaming, app_folder)
                    if os.path.exists(app_src_path):
                        self.log(f"Backing up Roaming AppData for: {app_folder}...")
                        self.copy_folder_with_logging(app_src_path, os.path.join(appdata_dest, "Roaming", app_folder), manifest)
                    
                    local_app_src = os.path.join(self.appdata_local, app_folder)
                    if os.path.exists(local_app_src):
                        self.log(f"Backing up Local AppData for: {app_folder}...")
                        self.copy_folder_with_logging(local_app_src, os.path.join(appdata_dest, "Local", app_folder), manifest)
            
            # 4. Registry Configuration
            elif cat_name == "Registry Configurations":
                reg_dest_dir = os.path.join(temp_dir, "registry")
                os.makedirs(reg_dest_dir, exist_ok=True)
                for index, reg_path in enumerate(registry_paths):
                    if not reg_path.strip():
                        continue
                    if self.cancel_event.is_set():
                        self.queue.put(("CANCELLED", None))
                        return
                    
                    # Sanitize path name for filename
                    safe_name = reg_path.replace("\\", "_").replace(":", "_").replace(" ", "_")[:64] + f"_{index}.reg"
                    reg_file_path = os.path.join(reg_dest_dir, safe_name)
                    
                    self.log(f"Exporting registry hive: {reg_path}...")
                    cmd = f'reg.exe export "{reg_path}" "{reg_file_path}" /y'
                    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    if res.returncode == 0:
                        self.log(f"Exported successfully to {safe_name}")
                        manifest["registry_keys_backed_up"].append({"key": reg_path, "file": safe_name})
                    else:
                        self.log(f"[WARNING] Failed to export registry key: {reg_path}. Error: {res.stderr.strip()}")
            
            manifest["categories"].append(cat_name)
            
        # Write manifest file
        manifest_path = os.path.join(temp_dir, "backup_manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=4)
            
        # 5. Zip it up
        self.log("Creating compressed archive...")
        self.set_progress(0.95)
        
        try:
            # Delete if exists
            if os.path.exists(target_zip_path):
                os.remove(target_zip_path)
            
            # Ensure target parent directory exists
            os.makedirs(os.path.dirname(target_zip_path), exist_ok=True)
            
            # Compress using zipfile (chunked file tracking is done under the hood, but we show zip status)
            with zipfile.ZipFile(target_zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        if self.cancel_event.is_set():
                            self.queue.put(("CANCELLED", None))
                            return
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zip_file.write(file_path, arcname)
                        
            self.set_progress(1.0)
            self.log(f"Backup completed successfully! Archive saved at: {target_zip_path}")
            
            # Cleanup temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            self.queue.put(("DONE", f"Backup complete!\nFiles backed up: {manifest['files_backed_up']}\nSaved to: {target_zip_path}"))
        except Exception as e:
            self.log(f"ERROR during archival: {e}")
            self.queue.put(("DONE", f"Error during archival: {e}"))

    def run_restore(self, zip_archive_path, selected_categories_to_restore):
        """Runs the restore process (License validation happens in GUI before calling this)."""
        self.set_progress(0.0)
        temp_restore_dir = os.path.join(self.appdata_local, "Temp", "MigrateKit_Temp_Restore")
        if os.path.exists(temp_restore_dir):
            shutil.rmtree(temp_restore_dir, ignore_errors=True)
        os.makedirs(temp_restore_dir, exist_ok=True)
        
        self.log(f"Extracting backup archive from: {zip_archive_path}")
        
        try:
            with zipfile.ZipFile(zip_archive_path, 'r') as zip_ref:
                zip_ref.extractall(temp_restore_dir)
        except Exception as e:
            self.log(f"ERROR: Failed to extract archive: {e}")
            self.queue.put(("DONE", f"Error: Extraction failed: {e}"))
            return
            
        manifest_path = os.path.join(temp_restore_dir, "backup_manifest.json")
        if not os.path.exists(manifest_path):
            self.log("ERROR: Invalid backup package. 'backup_manifest.json' is missing.")
            self.queue.put(("DONE", "Error: Missing manifest file"))
            return
            
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
            
        self.log(f"Successfully loaded backup manifest.")
        self.log(f"Backup details: Host={manifest.get('hostname')}, User={manifest.get('user')}, Date={manifest.get('timestamp')}")
        
        # Mapping standard restore paths
        user_dirs = {
            "Documents": os.path.join(self.user_profile, "Documents"),
            "Pictures": os.path.join(self.user_profile, "Pictures"),
            "Desktop": os.path.join(self.user_profile, "Desktop"),
            "Downloads": os.path.join(self.user_profile, "Downloads"),
            "Videos": os.path.join(self.user_profile, "Videos"),
            "Music": os.path.join(self.user_profile, "Music")
        }
        
        # Categories to restore based on what exists in the package and what's selected
        categories_in_package = manifest.get("categories", [])
        categories_to_restore = [c for c in categories_in_package if selected_categories_to_restore.get(c, False)]
        
        total_steps = len(categories_to_restore)
        if total_steps == 0:
            self.log("No selected categories match the data inside this backup package.")
            self.queue.put(("DONE", "Error: No matching categories to restore"))
            return
            
        current_step = 0
        
        for cat_name in categories_to_restore:
            if self.cancel_event.is_set():
                self.log("Restore cancelled by user.")
                self.queue.put(("CANCELLED", None))
                return
                
            current_step += 1
            self.log(f"[{current_step}/{total_steps}] Restoring {cat_name}...")
            self.set_progress(current_step / (total_steps + 1))
            
            # 1. Standard folders
            if cat_name in user_dirs:
                src_dir = os.path.join(temp_restore_dir, "data", cat_name)
                dest_dir = user_dirs[cat_name]
                if os.path.exists(src_dir):
                    self.restore_folder(src_dir, dest_dir)
                else:
                    self.log(f"[WARNING] Backup files for {cat_name} missing from zip archive.")
            
            # 2. Chrome Profile
            elif cat_name == "Chrome Profile":
                chrome_src = os.path.join(temp_restore_dir, "data", "Chrome")
                chrome_dest = os.path.join(self.appdata_local, "Google", "Chrome", "User Data")
                
                # Check if Chrome is running and kill it if necessary, or warn
                tasklist = subprocess.run("tasklist /FI \"IMAGENAME eq chrome.exe\"", shell=True, capture_output=True, text=True)
                if "chrome.exe" in tasklist.stdout:
                    self.log("[WARNING] Google Chrome is running. Attempting to restore to a locked directory can cause errors. Close Chrome.")
                
                if os.path.exists(chrome_src):
                    self.restore_folder(chrome_src, chrome_dest)
                    self.log("Chrome profile files restored.")
                else:
                    self.log("[WARNING] Chrome profile folder not found in backup.")
            
            # 3. Selective AppData
            elif cat_name == "Application Data (AppData)":
                appdata_src = os.path.join(temp_restore_dir, "data", "AppData")
                if os.path.exists(appdata_src):
                    # Roaming AppData
                    roaming_src = os.path.join(appdata_src, "Roaming")
                    if os.path.exists(roaming_src):
                        self.restore_folder(roaming_src, self.appdata_roaming)
                    
                    # Local AppData
                    local_src = os.path.join(appdata_src, "Local")
                    if os.path.exists(local_src):
                        self.restore_folder(local_src, self.appdata_local)
                        
                    self.log("Application data restored.")
                else:
                    self.log("[WARNING] Application Data not found in backup.")
                    
            # 4. Registry Configurations
            elif cat_name == "Registry Configurations":
                reg_src_dir = os.path.join(temp_restore_dir, "registry")
                reg_list = manifest.get("registry_keys_backed_up", [])
                
                if os.path.exists(reg_src_dir) and reg_list:
                    for reg_entry in reg_list:
                        if self.cancel_event.is_set():
                            self.queue.put(("CANCELLED", None))
                            return
                        filename = reg_entry.get("file")
                        reg_key = reg_entry.get("key")
                        file_path = os.path.join(reg_src_dir, filename)
                        
                        if os.path.exists(file_path):
                            self.log(f"Importing registry configuration for key: {reg_key}")
                            cmd = f'reg.exe import "{file_path}"'
                            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                            if res.returncode == 0:
                                self.log(f"Successfully imported: {filename}")
                            else:
                                self.log(f"[WARNING] Failed to import {filename}. Error: {res.stderr.strip()}")
                else:
                    self.log("[WARNING] Registry folder/configurations not found in backup.")
                    
        self.set_progress(1.0)
        self.log("Restore process completed.")
        
        # Cleanup temp directory
        shutil.rmtree(temp_restore_dir, ignore_errors=True)
        self.queue.put(("DONE", "Restore operation completed successfully! Check application logs for any skipped locked files."))

    def copy_folder_with_logging(self, src, dest, manifest):
        """Recursively copies folders while tracking file counts and handling locks."""
        if not os.path.exists(src):
            return
            
        os.makedirs(dest, exist_ok=True)
        
        for item in os.listdir(src):
            if self.cancel_event.is_set():
                return
                
            s_path = os.path.join(src, item)
            d_path = os.path.join(dest, item)
            
            if os.path.isdir(s_path):
                # Avoid looping inside backup directory if it happens to be a subfolder of source
                if os.path.abspath(s_path) == os.path.abspath(dest):
                    continue
                self.copy_folder_with_logging(s_path, d_path, manifest)
            else:
                try:
                    shutil.copy2(s_path, d_path)
                    manifest["files_backed_up"] += 1
                except Exception as e:
                    self.log(f"[LOCKED/SKIP] Could not copy file: {s_path}. Reason: {e}")

    def restore_folder(self, src, dest):
        """Recursively copies source files back to their target destination on restore."""
        if not os.path.exists(src):
            return
            
        os.makedirs(dest, exist_ok=True)
        
        for item in os.listdir(src):
            if self.cancel_event.is_set():
                return
                
            s_path = os.path.join(src, item)
            d_path = os.path.join(dest, item)
            
            if os.path.isdir(s_path):
                self.restore_folder(s_path, d_path)
            else:
                try:
                    # Overwrite if exists, fallback to standard copy
                    if os.path.exists(d_path):
                        os.remove(d_path)
                    shutil.copy2(s_path, d_path)
                except Exception as e:
                    self.log(f"[RESTORE ERROR/SKIP] Failed to restore file: {d_path}. Reason: {e}")


class MigrateKitApp(ctk.CTk):
    """Main CustomTkinter User Interface."""
    def __init__(self):
        super().__init__()
        
        self.title("MigrateKit — Windows 11 Migration Utility")
        self.geometry("950x620")
        self.minsize(900, 580)
        
        # Load license status
        self.is_activated, self.active_license = load_license_status()
        
        # Grid setup: Sidebar + Page Container
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        
        self.msg_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.engine = MigrationEngine(self.msg_queue, self.cancel_event)
        self.active_thread = None
        
        # Build layout
        self.create_sidebar()
        self.create_pages()
        
        # Set default view
        self.show_page("welcome")
        
        # Start queue poller
        self.poll_queue()

    def create_sidebar(self):
        """Creates the navigation sidebar."""
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(6, weight=1) # push settings/footer down
        
        # App Title
        self.logo = ctk.CTkLabel(
            self.sidebar, 
            text="MIGRATEKIT", 
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold")
        )
        self.logo.grid(row=0, column=0, padx=20, pady=(25, 20))
        
        # Sidebar Menu Buttons
        self.btn_welcome = ctk.CTkButton(
            self.sidebar, text="Dashboard", fg_color="transparent", text_color=("gray10", "gray90"),
            hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("welcome")
        )
        self.btn_welcome.grid(row=1, column=0, padx=15, pady=5, sticky="ew")
        
        self.btn_backup = ctk.CTkButton(
            self.sidebar, text="Backup Wizard", fg_color="transparent", text_color=("gray10", "gray90"),
            hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("backup")
        )
        self.btn_backup.grid(row=2, column=0, padx=15, pady=5, sticky="ew")
        
        self.btn_restore = ctk.CTkButton(
            self.sidebar, text="Restore Wizard", fg_color="transparent", text_color=("gray10", "gray90"),
            hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("restore")
        )
        self.btn_restore.grid(row=3, column=0, padx=15, pady=5, sticky="ew")
        
        self.btn_license = ctk.CTkButton(
            self.sidebar, text="License Activation", fg_color="transparent", text_color=("gray10", "gray90"),
            hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("license")
        )
        self.btn_license.grid(row=4, column=0, padx=15, pady=5, sticky="ew")
        
        self.btn_settings = ctk.CTkButton(
            self.sidebar, text="Settings & Info", fg_color="transparent", text_color=("gray10", "gray90"),
            hover_color=("gray70", "gray30"), anchor="w", command=lambda: self.show_page("settings")
        )
        self.btn_settings.grid(row=5, column=0, padx=15, pady=5, sticky="ew")
        
        # Status footer indicator
        self.lbl_license_status = ctk.CTkLabel(
            self.sidebar, 
            text="LOCKED" if not self.is_activated else "LICENSED", 
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#f43f5e" if not self.is_activated else "#10b981",
            fg_color=("gray85", "gray20"),
            corner_radius=4,
            height=24
        )
        self.lbl_license_status.grid(row=7, column=0, padx=20, pady=20, sticky="ew")

    def create_pages(self):
        """Creates individual frames for page switching."""
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.grid(row=0, column=1, sticky="nsew", padx=25, pady=25)
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)
        
        self.pages = {}
        
        # 1. Welcome Page
        welcome_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.pages["welcome"] = welcome_frame
        
        ctk.CTkLabel(
            welcome_frame, text="Windows 11 Migration Portal", 
            font=ctk.CTkFont(size=26, weight="bold")
        ).pack(anchor="w", pady=(10, 5))
        
        ctk.CTkLabel(
            welcome_frame, 
            text="Migrate your personal profile directories, Chrome browser configuration, application settings, and registry hives securely to a new Windows 11 installation.",
            text_color="gray60", font=ctk.CTkFont(size=13), justify="left", wraplength=600
        ).pack(anchor="w", pady=(0, 20))
        
        card_container = ctk.CTkFrame(welcome_frame, fg_color="transparent")
        card_container.pack(fill="both", expand=True)
        
        # Backup Card
        b_card = ctk.CTkFrame(card_container, width=310, height=350, corner_radius=12)
        b_card.pack(side="left", fill="both", expand=True, padx=(0, 10))
        b_card.pack_propagate(False)
        ctk.CTkLabel(b_card, text="📦", font=ctk.CTkFont(size=48)).pack(pady=(40, 10))
        ctk.CTkLabel(b_card, text="Package Backup", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=5)
        ctk.CTkLabel(
            b_card, text="Compress profile folders, browser details, specific app settings, and registry databases into a secure portable migration archive.",
            text_color="gray60", justify="center", wraplength=220
        ).pack(pady=10)
        ctk.CTkButton(b_card, text="Run Backup Wizard", command=lambda: self.show_page("backup")).pack(side="bottom", pady=30)
        
        # Restore Card
        r_card = ctk.CTkFrame(card_container, width=310, height=350, corner_radius=12)
        r_card.pack(side="right", fill="both", expand=True, padx=(10, 0))
        r_card.pack_propagate(False)
        ctk.CTkLabel(r_card, text="🚀", font=ctk.CTkFont(size=48)).pack(pady=(40, 10))
        ctk.CTkLabel(r_card, text="Extract & Restore", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=5)
        ctk.CTkLabel(
            r_card, text="Restore folder packages, browser database items, AppData settings, and register keys back into the fresh Windows 11 target directories.",
            text_color="gray60", justify="center", wraplength=220
        ).pack(pady=10)
        ctk.CTkButton(
            r_card, text="Run Restore Wizard", 
            command=lambda: self.show_page("restore"),
            fg_color="#10b981", hover_color="#059669"
        ).pack(side="bottom", pady=30)

        # 2. Backup Page
        backup_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.pages["backup"] = backup_frame
        
        ctk.CTkLabel(
            backup_frame, text="Backup Engine", 
            font=ctk.CTkFont(size=24, weight="bold")
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(5, 5))
        
        ctk.CTkLabel(
            backup_frame, text="Configure components to include in your portable migration archive:",
            text_color="gray60", font=ctk.CTkFont(size=12)
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 15))
        
        # Checkbox configuration columns
        checks_frame = ctk.CTkFrame(backup_frame, fg_color="transparent")
        checks_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(0, 15))
        
        self.backup_categories = {
            "Documents": ctk.BooleanVar(value=True),
            "Pictures": ctk.BooleanVar(value=True),
            "Desktop": ctk.BooleanVar(value=True),
            "Downloads": ctk.BooleanVar(value=False),
            "Videos": ctk.BooleanVar(value=False),
            "Music": ctk.BooleanVar(value=False),
            "Chrome Profile": ctk.BooleanVar(value=True),
            "Application Data (AppData)": ctk.BooleanVar(value=True),
            "Registry Configurations": ctk.BooleanVar(value=True)
        }
        
        row_idx = 0
        col_idx = 0
        for name, var in self.backup_categories.items():
            cb = ctk.CTkCheckBox(checks_frame, text=name, variable=var, font=ctk.CTkFont(size=12))
            cb.grid(row=row_idx, column=col_idx, padx=15, pady=8, sticky="w")
            col_idx += 1
            if col_idx > 2:
                col_idx = 0
                row_idx += 1
                
        # AppData Selective options (Common developer/productivity apps)
        self.selected_appdata = ["Discord", "Microsoft VS Code", "Zoom", "Slack", "Notion"]
        
        # Registry configurations edit/list box
        ctk.CTkLabel(
            backup_frame, text="Registry keys to export (one path per line):", 
            font=ctk.CTkFont(size=11, weight="bold")
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(5, 2))
        
        self.txt_registry_paths = ctk.CTkTextbox(backup_frame, height=55, font=ctk.CTkFont(family="Consolas", size=10))
        self.txt_registry_paths.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self.txt_registry_paths.insert(
            "1.0", 
            "HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\User Shell Folders\nHKEY_CURRENT_USER\\Environment"
        )
        
        # Destination Folder Selector
        dest_lbl = ctk.CTkLabel(backup_frame, text="Save Archive Destination Path:", font=ctk.CTkFont(size=11, weight="bold"))
        dest_lbl.grid(row=5, column=0, columnspan=2, sticky="w", pady=(5, 2))
        
        dest_select_frame = ctk.CTkFrame(backup_frame, fg_color="transparent")
        dest_select_frame.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 15))
        dest_select_frame.grid_columnconfigure(0, weight=1)
        
        self.ent_backup_dest = ctk.CTkEntry(dest_select_frame, placeholder_text="c:\\Users\\YourUser\\Desktop\\migration_archive.migratekit")
        self.ent_backup_dest.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.ent_backup_dest.insert(0, os.path.join(self.user_profile, "Desktop", "MigrateKit_Backup.migratekit"))
        
        btn_browse_dest = ctk.CTkButton(dest_select_frame, text="Browse", width=80, command=self.browse_backup_dest)
        btn_browse_dest.grid(row=0, column=1)
        
        # Backup actions
        action_frame = ctk.CTkFrame(backup_frame, fg_color="transparent")
        action_frame.grid(row=7, column=0, columnspan=2, sticky="ew", pady=10)
        action_frame.grid_columnconfigure(0, weight=1)
        
        self.btn_run_backup = ctk.CTkButton(
            action_frame, text="Execute Backup Package", 
            command=self.start_backup_process, 
            height=36, font=ctk.CTkFont(weight="bold")
        )
        self.btn_run_backup.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        
        self.btn_cancel_backup = ctk.CTkButton(
            action_frame, text="Cancel", state="disabled", 
            command=self.cancel_operation, 
            height=36, fg_color="#f43f5e", hover_color="#e11d48", width=100
        )
        self.btn_cancel_backup.grid(row=0, column=1)

        # 3. Restore Page (Paywall Restricted)
        restore_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.pages["restore"] = restore_frame
        
        self.lbl_restore_title = ctk.CTkLabel(
            restore_frame, text="Restore Engine", 
            font=ctk.CTkFont(size=24, weight="bold")
        )
        self.lbl_restore_title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(5, 5))
        
        ctk.CTkLabel(
            restore_frame, text="Extract profile data, registry configs, and application folders from a backup file:",
            text_color="gray60", font=ctk.CTkFont(size=12)
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 15))
        
        # Paywall Guard banner
        self.paywall_banner = ctk.CTkFrame(restore_frame, fg_color=("#fee2e2", "#311c1c"), corner_radius=8, height=70)
        self.paywall_banner.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 15))
        self.paywall_banner.grid_propagate(False)
        
        self.paywall_icon = ctk.CTkLabel(self.paywall_banner, text="🔒", font=ctk.CTkFont(size=26))
        self.paywall_icon.pack(side="left", padx=15)
        
        self.paywall_text = ctk.CTkLabel(
            self.paywall_banner, 
            text="RESTORE LOCKED: To extract files, you must purchase a license key. Backups are always free, but importing profile data requires active license verification.",
            text_color=("#b91c1c", "#fca5a5"), font=ctk.CTkFont(size=11, weight="bold"),
            justify="left", wraplength=520
        )
        self.paywall_text.pack(side="left", pady=10, fill="both", expand=True)
        
        # File Source Selection
        src_lbl = ctk.CTkLabel(restore_frame, text="Select Migration Archive (.migratekit):", font=ctk.CTkFont(size=11, weight="bold"))
        src_lbl.grid(row=3, column=0, columnspan=2, sticky="w", pady=(5, 2))
        
        src_select_frame = ctk.CTkFrame(restore_frame, fg_color="transparent")
        src_select_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 15))
        src_select_frame.grid_columnconfigure(0, weight=1)
        
        self.ent_restore_src = ctk.CTkEntry(src_select_frame, placeholder_text="Select your .migratekit file...")
        self.ent_restore_src.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        
        self.btn_browse_src = ctk.CTkButton(src_select_frame, text="Browse", width=80, command=self.browse_restore_src)
        self.btn_browse_src.grid(row=0, column=1)
        
        # Checkboxes for selective restore
        ctk.CTkLabel(restore_frame, text="Elements to restore:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=5, column=0, columnspan=2, sticky="w", pady=(5, 2))
        restore_checks_frame = ctk.CTkFrame(restore_frame, fg_color="transparent")
        restore_checks_frame.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=(0, 15))
        
        self.restore_categories = {
            "Documents": ctk.BooleanVar(value=True),
            "Pictures": ctk.BooleanVar(value=True),
            "Desktop": ctk.BooleanVar(value=True),
            "Downloads": ctk.BooleanVar(value=False),
            "Videos": ctk.BooleanVar(value=False),
            "Music": ctk.BooleanVar(value=False),
            "Chrome Profile": ctk.BooleanVar(value=True),
            "Application Data (AppData)": ctk.BooleanVar(value=True),
            "Registry Configurations": ctk.BooleanVar(value=True)
        }
        
        row_idx = 0
        col_idx = 0
        for name, var in self.restore_categories.items():
            cb = ctk.CTkCheckBox(restore_checks_frame, text=name, variable=var, font=ctk.CTkFont(size=12))
            cb.grid(row=row_idx, column=col_idx, padx=15, pady=8, sticky="w")
            col_idx += 1
            if col_idx > 2:
                col_idx = 0
                row_idx += 1
                
        # Restore actions
        restore_action_frame = ctk.CTkFrame(restore_frame, fg_color="transparent")
        restore_action_frame.grid(row=7, column=0, columnspan=2, sticky="ew", pady=10)
        restore_action_frame.grid_columnconfigure(0, weight=1)
        
        self.btn_run_restore = ctk.CTkButton(
            restore_action_frame, text="Execute System Restore", 
            command=self.start_restore_process, 
            height=36, font=ctk.CTkFont(weight="bold"),
            fg_color="#10b981", hover_color="#059669"
        )
        self.btn_run_restore.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        
        self.btn_cancel_restore = ctk.CTkButton(
            restore_action_frame, text="Cancel", state="disabled", 
            command=self.cancel_operation, 
            height=36, fg_color="#f43f5e", hover_color="#e11d48", width=100
        )
        self.btn_cancel_restore.grid(row=0, column=1)

        # Update visual display of paywall
        self.update_restore_lock_state()

        # 4. License Activation Page
        license_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.pages["license"] = license_frame
        
        ctk.CTkLabel(
            license_frame, text="License Key Activation", 
            font=ctk.CTkFont(size=24, weight="bold")
        ).pack(anchor="w", pady=(5, 5))
        
        ctk.CTkLabel(
            license_frame, 
            text="Provide your 20-digit license code below. Once validated, system restoration features will unlock immediately.",
            text_color="gray60", font=ctk.CTkFont(size=12), justify="left"
        ).pack(anchor="w", pady=(0, 20))
        
        # Current status card
        self.status_card = ctk.CTkFrame(license_frame, height=90)
        self.status_card.pack(fill="x", pady=10)
        
        self.lbl_card_status = ctk.CTkLabel(
            self.status_card, 
            text="STATUS: LOCKED / UNREGISTERED", 
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#f43f5e"
        )
        self.lbl_card_status.pack(pady=(20, 5))
        
        self.lbl_license_type = ctk.CTkLabel(
            self.status_card, 
            text="Purchase a license on the storefront website to activate product features.",
            text_color="gray50", font=ctk.CTkFont(size=11)
        )
        self.lbl_license_type.pack(pady=(0, 15))
        
        # Key insertion
        ctk.CTkLabel(license_frame, text="Enter License Key:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(15, 5))
        
        self.ent_license_key = ctk.CTkEntry(
            license_frame, 
            placeholder_text="XXXXX-XXXXX-XXXXX-XXXXX", 
            font=ctk.CTkFont(family="Consolas", size=14),
            height=38
        )
        self.ent_license_key.pack(fill="x", pady=5)
        
        self.btn_activate_key = ctk.CTkButton(
            license_frame, text="Verify and Register License", 
            height=38, font=ctk.CTkFont(weight="bold"),
            command=self.activate_license_key
        )
        self.btn_activate_key.pack(fill="x", pady=15)
        
        # If already activated on launch, show key
        if self.is_activated:
            self.ent_license_key.insert(0, self.active_license)
            self.update_activation_ui("Standard License" if "DEVKEY" not in self.active_license else "Developer Bypass License")

        # 5. Settings & About Page
        settings_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.pages["settings"] = settings_frame
        
        ctk.CTkLabel(
            settings_frame, text="Settings & Utility Information", 
            font=ctk.CTkFont(size=24, weight="bold")
        ).pack(anchor="w", pady=(5, 5))
        
        ctk.CTkLabel(
            settings_frame, text="App options, system statistics, and technical configurations.",
            text_color="gray60", font=ctk.CTkFont(size=12)
        ).pack(anchor="w", pady=(0, 20))
        
        # Appearance Options
        theme_frame = ctk.CTkFrame(settings_frame)
        theme_frame.pack(fill="x", pady=10, padx=2)
        
        ctk.CTkLabel(
            theme_frame, text="Appearance color theme:", 
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(side="left", padx=20, pady=15)
        
        self.theme_menu = ctk.CTkOptionMenu(
            theme_frame, 
            values=["Dark", "Light", "System"],
            command=self.change_appearance_mode
        )
        self.theme_menu.pack(side="right", padx=20, pady=15)
        
        # System status cards
        info_frame = ctk.CTkFrame(settings_frame)
        info_frame.pack(fill="both", expand=True, pady=10, padx=2)
        
        ctk.CTkLabel(
            info_frame, text="System Architecture Summary", 
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=20, pady=(15, 10))
        
        details = (
            f"OS Platform: {sys.platform.upper()} (Windows 11 Compatible)\n"
            f"User profile directory: {self.user_profile}\n"
            f"AppData Roaming: {self.appdata_roaming}\n"
            f"AppData Local: {self.appdata_local}\n"
            f"Temporary storage directory: {os.path.join(self.appdata_local, 'Temp')}"
        )
        
        ctk.CTkLabel(
            info_frame, text=details, 
            justify="left", font=ctk.CTkFont(family="Consolas", size=11),
            text_color="gray60"
        ).pack(anchor="w", padx=20, pady=(0, 20))

        # Shared Console Log Panel at bottom of UI
        self.log_panel = ctk.CTkFrame(self, height=130, corner_radius=6)
        self.log_panel.grid(row=1, column=0, columnspan=2, sticky="ew", padx=25, pady=(0, 25))
        self.log_panel.grid_propagate(False)
        self.log_panel.grid_rowconfigure(0, weight=1)
        self.log_panel.grid_columnconfigure(0, weight=1)
        
        self.txt_log = ctk.CTkTextbox(
            self.log_panel, 
            fg_color=("gray90", "gray15"), 
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color=("gray10", "gray85")
        )
        self.txt_log.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.txt_log.configure(state="disabled")
        
        # Progress bar
        self.progress_bar = ctk.CTkProgressBar(self, height=8, corner_radius=0)
        self.progress_bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.progress_bar.set(0.0)

    def change_appearance_mode(self, new_mode):
        """Sets light/dark theme."""
        ctk.set_appearance_mode(new_mode)

    def show_page(self, page_name):
        """Switches visibility of panels."""
        for frame in self.pages.values():
            frame.grid_forget()
        self.pages[page_name].grid(row=0, column=0, sticky="nsew")
        
        # Highlight current sidebar menu button
        self.btn_welcome.configure(fg_color="transparent")
        self.btn_backup.configure(fg_color="transparent")
        self.btn_restore.configure(fg_color="transparent")
        self.btn_license.configure(fg_color="transparent")
        self.btn_settings.configure(fg_color="transparent")
        
        if page_name == "welcome":
            self.btn_welcome.configure(fg_color=("gray75", "gray25"))
        elif page_name == "backup":
            self.btn_backup.configure(fg_color=("gray75", "gray25"))
        elif page_name == "restore":
            self.btn_restore.configure(fg_color=("gray75", "gray25"))
        elif page_name == "license":
            self.btn_license.configure(fg_color=("gray75", "gray25"))
        elif page_name == "settings":
            self.btn_settings.configure(fg_color=("gray75", "gray25"))

    def log_message(self, text):
        """Writes messages to console panel."""
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"[{time.strftime('%H:%M:%S')}] {text}\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def browse_backup_dest(self):
        """Opens File Dialog for backup destination."""
        path = filedialog.asksaveasfilename(
            title="Save Migration Archive",
            defaultextension=".migratekit",
            filetypes=[("MigrateKit Package", "*.migratekit")]
        )
        if path:
            self.ent_backup_dest.delete(0, "end")
            self.ent_backup_dest.insert(0, path)

    def browse_restore_src(self):
        """Opens File Dialog to select backup file."""
        path = filedialog.askopenfilename(
            title="Open Migration Archive",
            filetypes=[("MigrateKit Package", "*.migratekit")]
        )
        if path:
            self.ent_restore_src.delete(0, "end")
            self.ent_restore_src.insert(0, path)

    def update_restore_lock_state(self):
        """Locks or unlocks Restore buttons based on activation state."""
        if self.is_activated:
            self.paywall_banner.grid_forget()
            self.btn_run_restore.configure(state="normal", text="Execute System Restore")
        else:
            self.paywall_banner.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 15))
            self.btn_run_restore.configure(state="disabled", text="Execute System Restore (LOCKED)")

    def activate_license_key(self):
        """Validates key inputted by user."""
        key = self.ent_license_key.get().strip()
        if not key:
            messagebox.showerror("Activation Error", "License key field cannot be empty.")
            return
            
        success, details = verify_license_key(key)
        if success:
            self.is_activated = True
            self.active_license = key
            save_license_status(key, True)
            self.update_activation_ui(details)
            self.update_restore_lock_state()
            messagebox.showinfo("Activation Successful", f"MigrateKit successfully unlocked!\nLicense Level: {details}")
        else:
            messagebox.showerror("Activation Failed", f"Validation error: {details}")

    def update_activation_ui(self, license_type):
        """Refreshes status strings when activated."""
        self.lbl_license_status.configure(text="LICENSED", text_color="#10b981")
        self.lbl_card_status.configure(text=f"STATUS: ACTIVATED ({license_type.upper()})", text_color="#10b981")
        self.lbl_license_type.configure(text=f"Licensed to machine configuration: {os.environ.get('COMPUTERNAME', 'Default Host')}")

    def start_backup_process(self):
        """Spawns backup thread."""
        target_path = self.ent_backup_dest.get().strip()
        if not target_path:
            messagebox.showerror("Backup Error", "Destination folder path is required.")
            return
            
        cats = {k: v.get() for k, v in self.backup_categories.items()}
        reg_paths = self.txt_registry_paths.get("1.0", "end").strip().split("\n")
        
        self.cancel_event.clear()
        self.btn_run_backup.configure(state="disabled")
        self.btn_cancel_backup.configure(state="normal")
        self.progress_bar.set(0.0)
        
        self.active_thread = threading.Thread(
            target=self.engine.run_backup,
            args=(target_path, cats, self.selected_appdata, reg_paths),
            daemon=True
        )
        self.active_thread.start()

    def start_restore_process(self):
        """Spawns restore thread if licensed."""
        if not self.is_activated:
            messagebox.showwarning("Feature Locked", "System restoration is locked. Provide a valid license key.")
            self.show_page("license")
            return
            
        archive_path = self.ent_restore_src.get().strip()
        if not archive_path or not os.path.exists(archive_path):
            messagebox.showerror("Restore Error", "Select a valid backup file (.migratekit).")
            return
            
        cats = {k: v.get() for k, v in self.restore_categories.items()}
        
        self.cancel_event.clear()
        self.btn_run_restore.configure(state="disabled")
        self.btn_cancel_restore.configure(state="normal")
        self.progress_bar.set(0.0)
        
        self.active_thread = threading.Thread(
            target=self.engine.run_restore,
            args=(archive_path, cats),
            daemon=True
        )
        self.active_thread.start()

    def cancel_operation(self):
        """Triggers event cancellation."""
        self.log_message("Triggering operation cancel...")
        self.cancel_event.set()

    def poll_queue(self):
        """Polls background messages to update UI variables."""
        try:
            while True:
                msg_type, data = self.msg_queue.get_nowait()
                if msg_type == "LOG":
                    self.log_message(data)
                elif msg_type == "PROGRESS":
                    self.progress_bar.set(data)
                elif msg_type == "DONE":
                    self.progress_bar.set(1.0)
                    messagebox.showinfo("Process Finished", data)
                    self.reset_action_buttons()
                elif msg_type == "CANCELLED":
                    self.progress_bar.set(0.0)
                    self.log_message("Operation successfully cancelled.")
                    messagebox.showwarning("Cancelled", "Process was cancelled by user.")
                    self.reset_action_buttons()
        except queue.Empty:
            pass
        self.after(100, self.poll_queue)

    def reset_action_buttons(self):
        """Resets run/cancel buttons after run thread completes."""
        self.btn_run_backup.configure(state="normal")
        self.btn_cancel_backup.configure(state="disabled")
        self.btn_run_restore.configure(state="normal")
        self.btn_cancel_restore.configure(state="disabled")
        self.update_restore_lock_state()

if __name__ == "__main__":
    app = MigrateKitApp()
    app.mainloop()
