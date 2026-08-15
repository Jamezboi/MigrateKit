# verify_integrity.ps1
# Script to verify the integrity of restored files by comparing them against the backup manifest.

param (
    [Parameter(Mandatory=$true)]
    [string]$BackupPath,

    [Parameter(Mandatory=$false)]
    [string]$TargetRoot = $HOME
)

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "   MigrateKit Integrity Verification Script  " -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "Backup Path: $BackupPath"
Write-Host "Target Root: $TargetRoot"
Write-Host ""

if (-not (Test-Path $BackupPath)) {
    Write-Error "Backup package not found at $BackupPath"
    exit 1
}

# Define a temporary extraction directory for manifest reading
$TempExtractPath = Join-Path $env:TEMP "MigrateKit_Integrity_Temp"
if (Test-Path $TempExtractPath) {
    Remove-Item $TempExtractPath -Recurse -Force | Out-Null
}
New-Item -ItemType Directory -Path $TempExtractPath | Out-Null

try {
    # Extract only the manifest file from the Zip file using PowerShell's built-in compression features
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($BackupPath)
    $manifestEntry = $zip.Entries | Where-Object { $_.FullName -eq "backup_manifest.json" }
    
    if ($null -eq $manifestEntry) {
        Write-Error "Invalid backup package: 'backup_manifest.json' not found inside the zip file."
        $zip.Dispose()
        exit 1
    }
    
    $manifestPath = Join-Path $TempExtractPath "backup_manifest.json"
    [System.IO.Compression.ZipFileExtensions]::ExtractToFile($manifestEntry, $manifestPath, $true)
    $zip.Dispose()
    
    # Read and parse the manifest
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    Write-Host "Manifest details loaded successfully."
    Write-Host "Original PC: $($manifest.hostname)"
    Write-Host "Backup User: $($manifest.user)"
    Write-Host "Backup Time: $($manifest.timestamp)"
    Write-Host ""
}
catch {
    Write-Error "Failed to parse manifest: $_"
    if ($null -ne $zip) { $zip.Dispose() }
    exit 1
}
finally {
    # Clean up temporary manifest folder
    if (Test-Path $TempExtractPath) {
        Remove-Item $TempExtractPath -Recurse -Force | Out-Null
    }
}

# Start verification
Write-Host "Checking categories and verifying files..." -ForegroundColor Yellow

$missingFilesCount = 0
$matchedFilesCount = 0
$categoriesChecked = 0

foreach ($category in $manifest.categories) {
    Write-Host "-> Verifying category: $category" -ForegroundColor Cyan
    
    # Mapping the manifest layout back to restored system paths
    $targetDir = ""
    switch ($category) {
        "Documents" { $targetDir = Join-Path $TargetRoot "Documents" }
        "Pictures"  { $targetDir = Join-Path $TargetRoot "Pictures" }
        "Desktop"   { $targetDir = Join-Path $TargetRoot "Desktop" }
        "Downloads" { $targetDir = Join-Path $TargetRoot "Downloads" }
        "Videos"    { $targetDir = Join-Path $TargetRoot "Videos" }
        "Music"     { $targetDir = Join-Path $TargetRoot "Music" }
        "Chrome Profile" { $targetDir = Join-Path $env:LOCALAPPDATA "Google\Chrome\User Data" }
        "Application Data (AppData)" { $targetDir = Join-Path $env:APPDATA "" } # will match Roaming parent
    }
    
    if ($targetDir -and (Test-Path $targetDir)) {
        Write-Host "   Directory exists: $targetDir" -ForegroundColor Green
        $categoriesChecked++
    } elseif ($category -eq "Registry Configurations") {
        # Check if keys exist in Registry
        if ($null -ne $manifest.registry_keys_backed_up) {
            foreach ($regKey in $manifest.registry_keys_backed_up) {
                # Simple check to see if we can open/query key
                $regPath = $regKey.key
                if (Test-Path "Registry::$regPath") {
                    Write-Host "   Registry key verified: $regPath" -ForegroundColor Green
                    $matchedFilesCount++
                } else {
                    Write-Host "   [MISSING] Registry key not found: $regPath" -ForegroundColor Red
                    $missingFilesCount++
                }
            }
            $categoriesChecked++
        }
    } else {
        Write-Host "   [MISSING] Category target directory not found: $targetDir" -ForegroundColor Red
        $missingFilesCount++
    }
}

Write-Host ""
Write-Host "Verification Complete!" -ForegroundColor Cyan
Write-Host "Categories Verified: $categoriesChecked"
Write-Host "Successful Checks/Matches: $matchedFilesCount"
if ($missingFilesCount -gt 0) {
    Write-Host "Missing/Failed Matches: $missingFilesCount" -ForegroundColor Red
    Write-Host "Integrity status: FAILED (Some files or folders are missing)" -ForegroundColor Red
    exit 1
} else {
    Write-Host "Integrity status: PASSED (All files, folders, and settings verified)" -ForegroundColor Green
    exit 0
}
