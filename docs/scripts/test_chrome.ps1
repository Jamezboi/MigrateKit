# test_chrome.ps1
# Script to verify the integrity and structure of the restored Google Chrome profile.

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "   MigrateKit Google Chrome Profile Validator" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

$ChromeUserData = Join-Path $env:LOCALAPPDATA "Google\Chrome\User Data"
$DefaultProfile = Join-Path $ChromeUserData "Default"

# 1. Check folder existence
if (-not (Test-Path $DefaultProfile)) {
    Write-Host "[-] Google Chrome Default profile folder not found at: $DefaultProfile" -ForegroundColor Red
    Write-Host "    Validation Status: FAILED" -ForegroundColor Red
    exit 1
}
Write-Host "[+] Chrome Default profile folder located successfully." -ForegroundColor Green

# 2. Check Bookmarks file
$bookmarksPath = Join-Path $DefaultProfile "Bookmarks"
if (-not (Test-Path $bookmarksPath)) {
    Write-Host "[-] Bookmarks file is missing." -ForegroundColor Red
    $bookmarksValid = $false
} else {
    try {
        # Bookmarks is a JSON file, parse to verify validity
        $bookmarksContent = Get-Content $bookmarksPath -Raw | ConvertFrom-Json
        $bookmarkCount = 0
        if ($null -ne $bookmarksContent.roots.bookmark_bar.children) {
            $bookmarkCount += $bookmarksContent.roots.bookmark_bar.children.Count
        }
        if ($null -ne $bookmarksContent.roots.other.children) {
            $bookmarkCount += $bookmarksContent.roots.other.children.Count
        }
        
        Write-Host "[+] Bookmarks file is valid JSON. Found $bookmarkCount bookmark(s)." -ForegroundColor Green
        $bookmarksValid = $true
    }
    catch {
        Write-Host "[-] Bookmarks file exists but failed JSON parsing. It may be corrupt: $_" -ForegroundColor Red
        $bookmarksValid = $false
    }
}

# 3. Check SQLite History Database Signature
$historyPath = Join-Path $DefaultProfile "History"
$historyValid = $false

if (-not (Test-Path $historyPath)) {
    Write-Host "[-] Chrome History database file is missing." -ForegroundColor Red
} else {
    try {
        # Check SQLite header signature: First 15 bytes must equal "SQLite format 3"
        $fileStream = [System.IO.File]::OpenRead($historyPath)
        $buffer = New-Object byte[] 16
        $bytesRead = $fileStream.Read($buffer, 0, 16)
        $fileStream.Close()
        
        $headerString = [System.Text.Encoding]::UTF8.GetString($buffer)
        if ($headerString.StartsWith("SQLite format 3")) {
            Write-Host "[+] Chrome History SQLite database signature is valid." -ForegroundColor Green
            $historyValid = $true
        } else {
            Write-Host "[-] History file is present but has an invalid SQLite header: '$headerString'" -ForegroundColor Red
        }
    }
    catch {
        Write-Host "[-] Failed to read Chrome History file header: $_" -ForegroundColor Red
    }
}

# 4. Check Login Data (Credentials Database)
$loginDataPath = Join-Path $DefaultProfile "Login Data"
$loginValid = $false

if (-not (Test-Path $loginDataPath)) {
    Write-Host "[-] Chrome Login Data (Passwords) file is missing." -ForegroundColor Red
} else {
    try {
        $fileStream = [System.IO.File]::OpenRead($loginDataPath)
        $buffer = New-Object byte[] 16
        $bytesRead = $fileStream.Read($buffer, 0, 16)
        $fileStream.Close()
        
        $headerString = [System.Text.Encoding]::UTF8.GetString($buffer)
        if ($headerString.StartsWith("SQLite format 3")) {
            Write-Host "[+] Chrome Login Data SQLite database signature is valid." -ForegroundColor Green
            $loginValid = $true
        } else {
            Write-Host "[-] Login Data file is present but has an invalid SQLite header: '$headerString'" -ForegroundColor Red
        }
    }
    catch {
        Write-Host "[-] Failed to read Chrome Login Data file header: $_" -ForegroundColor Red
    }
}

# Overall status check
Write-Host ""
if ($bookmarksValid -and $historyValid -and $loginValid) {
    Write-Host "Chrome Profile Integrity: PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "Chrome Profile Integrity: FAILED (Check missing files or structure problems noted above)" -ForegroundColor Red
    exit 1
}
