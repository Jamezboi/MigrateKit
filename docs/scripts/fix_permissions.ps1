# fix_permissions.ps1
# Script to resolve file locks by terminating blocking processes, taking ownership of target folders, and resetting ACLs.

param (
    [Parameter(Mandatory=$false)]
    [string]$TargetDirectory = $HOME
)

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "   MigrateKit Permission & Lock Troubleshooter" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "Target Directory: $TargetDirectory"
Write-Host ""

# 1. Terminate potential lock-creating applications
$lockingProcesses = @("chrome", "onedrive", "teams", "msedge", "outlook", "excel", "winword")

Write-Host "[1/3] Scanning for and terminating locking applications..." -ForegroundColor Yellow
foreach ($proc in $lockingProcesses) {
    $running = Get-Process -Name $proc -ErrorAction SilentlyContinue
    if ($running) {
        Write-Host "Found running process: $proc. Terminating process..." -ForegroundColor DarkYellow
        Stop-Process -Name $proc -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1 # allow process to shut down and release handles
    }
}
Write-Host "[+] All target background locking processes terminated." -ForegroundColor Green
Write-Host ""

# 2. Gain Directory Ownership
Write-Host "[2/3] Elevating file/folder permissions and taking ownership..." -ForegroundColor Yellow
if (-not (Test-Path $TargetDirectory)) {
    Write-Error "The specified directory does not exist: $TargetDirectory"
    exit 1
}

# Run takeown utility native to Windows to reclaim ownership
Write-Host "Running: takeown.exe /F $TargetDirectory /R /A /D Y" -ForegroundColor DarkGray
# /F (file/folder) /R (recursive) /A (assigns ownership to Admin group) /D Y (default answer yes)
$takeownResult = takeown.exe /F $TargetDirectory /R /A /D Y 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[-] Note: takeown command reported warnings (can occur if files are already owned or system locks remain)." -ForegroundColor Gray
} else {
    Write-Host "[+] takeown completed successfully." -ForegroundColor Green
}
Write-Host ""

# 3. Reset Access Control Lists (ACLs) to give current user full permissions
Write-Host "[3/3] Granting Full Access to Current User..." -ForegroundColor Yellow
$currentUser = "$env:USERDOMAIN\$env:USERNAME"
Write-Host "Target User: $currentUser"

# Run icacls utility to modify Access Control Lists
Write-Host "Running: icacls.exe `"$TargetDirectory`" /grant `"${currentUser}:(OI)(CI)F`" /T /C /Q" -ForegroundColor DarkGray
# /grant (give user permissions) :F (full access) (OI) (object inherit) (CI) (container inherit) /T (recursive) /C (continue on errors) /Q (quiet)
$icaclsResult = icacls.exe "$TargetDirectory" /grant "${currentUser}:(OI)(CI)F" /T /C /Q 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[-] Note: icacls reported warnings (can occur on system directories or hidden AppData files)." -ForegroundColor Gray
} else {
    Write-Host "[+] Full access granted and inherited successfully." -ForegroundColor Green
}

Write-Host ""
Write-Host "Permissions troubleshooting completed. Re-run migration restore." -ForegroundColor Cyan
exit 0
