# MigrateKit VM Testing & Troubleshooting Guide

This guide outlines the protocol for testing the MigrateKit migration engine in a sandboxed Virtual Machine (VM) and details troubleshooting procedures for common migration issues.

---

## 1. Environment Setup

To verify profile and registry restoration safely, we recommend using a fresh Windows 11 Virtual Machine using either VirtualBox (cross-platform) or Hyper-V (Windows native).

### Method A: VirtualBox Configuration
1. **Download & Install**: Install the latest version of [VirtualBox](https://www.virtualbox.org/) and the VirtualBox Extension Pack.
2. **Obtain ISO**: Download the Windows 11 ISO from the [Microsoft Official Download Page](https://www.microsoft.com/software-download/windows11).
3. **Bypass Win11 System Checks (TPM/RAM)**:
   - When starting the Windows installation in the VM, press `Shift + F10` to open a command prompt.
   - Type `regedit.exe` and press Enter.
   - Navigate to `HKEY_LOCAL_MACHINE\SYSTEM\Setup`.
   - Create a new Key named `LabConfig`.
   - Under `LabConfig`, create the following DWORD (32-bit) values set to `1`:
     - `BypassTPMCheck`
     - `BypassSecureBootCheck`
     - `BypassRAMCheck`
   - Close Regedit and proceed with the installation.
4. **VM Specifications**:
   - **RAM**: Minimum 4096 MB (4 GB).
   - **Processors**: Minimum 2 CPUs.
   - **Disk Space**: At least 60 GB dynamically allocated.
5. **Install Guest Additions**:
   - Once Windows 11 is booted, click **Devices** > **Insert Guest Additions CD Image** in the VirtualBox menu.
   - Open File Explorer in the VM, run the installer on the CD drive, and reboot.
6. **Set up Shared Folders**:
   - Go to VM settings > **Shared Folders**.
   - Add a folder path pointing to your host migration folder containing `.migratekit` files.
   - Check **Auto-mount** and **Make Permanent**. It will show up under `Z:` or in Network locations inside the VM.

### Method B: Hyper-V Configuration
1. **Enable Hyper-V**: Run PowerShell as administrator and execute:
   ```powershell
   Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All
   ```
   Reboot your PC when prompted.
2. **Create Gen 2 VM**:
   - Open Hyper-V Manager > **New** > **Virtual Machine**.
   - Select **Generation 2** (Required for UEFI and Windows 11).
   - Configure memory (4096 MB) and connect to a virtual switch.
   - Enable **Secure Boot** in the VM settings (Security tab) and select the **Microsoft Windows** template.
   - Enable **TPM** support under the Security tab.
3. **Enhanced Session Mode**:
   - Turn on Enhanced Session Mode in Hyper-V settings to allow clipboard copying and local resource redirection (enables simple drag-and-drop file transfer of the `.migratekit` archive).

---

## 2. Test Protocol

Follow these steps to perform end-to-end verification of the migration process.

### Step 1: Create a Sandbox Profile (Host)
Before running the backup, make sure you have some dummy profile data on the host machine to test:
- Create a text file on the host Desktop: `Desktop\Test_Doc.txt`.
- Add a couple of dummy bookmarks in Google Chrome.
- Install a small application like VS Code or Discord to verify AppData transfer.

### Step 2: Run the Backup (Host)
1. Launch `MigrateKit.exe` or run `python migratekit.py` on your host.
2. Select **Backup Wizard**.
3. Check the directories you want to package (e.g., Documents, Desktop, Chrome Profile, Registry).
4. Run the backup to create a `.migratekit` file (e.g. on your Desktop).

### Step 3: Configure clean VM state
1. Power up the Windows 11 VM.
2. Create a virtual machine **Snapshot** (named "Clean State") before running any restoration tools. This allows you to restore, test, and instantly revert to a clean OS for repeated testing.

### Step 4: Execute Restoration (VM)
1. Copy the `.migratekit` file and the compiled `MigrateKit.exe` into the VM (via Shared Folder or Enhanced Session clipboard).
2. Run `MigrateKit.exe` inside the VM.
3. Navigate to **License Activation** and enter the developer bypass key:
   ```
   DEVKEY-MIGRATE-2026-UNLOCK
   ```
4. Navigate to **Restore Wizard**, select the `.migratekit` file, check the desired restoration categories, and click **Execute System Restore**.

---

## 3. Troubleshooting & Scripts

Permission errors, locked files, and database access locks are common occurrences during migration. Included in the `docs/scripts/` folder are three scripts to automate troubleshooting:

### A. Integrity Verification (`verify_integrity.ps1`)
Runs in the VM to check if all files defined in the backup manifest were successfully copied and match their original metadata size.
- **Run Command**:
  ```powershell
  PowerShell.exe -ExecutionPolicy Bypass -File .\verify_integrity.ps1 -BackupPath "C:\Path\To\archive.migratekit" -TargetRoot "$HOME"
  ```

### B. Chrome Profile Validation (`test_chrome.ps1`)
Verifies if Chrome files successfully populated and validates the integrity of the SQLite database files (such as History) without opening Chrome itself.
- **Run Command**:
  ```powershell
  PowerShell.exe -ExecutionPolicy Bypass -File .\test_chrome.ps1
  ```

### C. Permissions & Lock Troubleshooter (`fix_permissions.ps1`)
Locks happen if Chrome or OneDrive are actively running when writing to user directories. This script forcefully closes locking processes, claims ownership of target directories, and resets Access Control Lists (ACLs) to ensure files are writeable.
- **Run Command**:
  ```powershell
  PowerShell.exe -ExecutionPolicy Bypass -File .\fix_permissions.ps1 -TargetDirectory "$HOME\Documents"
  ```
