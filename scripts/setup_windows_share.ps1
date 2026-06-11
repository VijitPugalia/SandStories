# Setup Windows Network Share for SandStories IPA
# This script must be run as Administrator.

$ShareName = "SandStoriesIPA"
$Path = "C:\Users\vijit\SandStoriesIPA"
$Username = "vijit"

# Check if running as Admin
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Warning "This script is not running as Administrator. Attempting to relaunch with elevation..."
    Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    Exit
}

# Create folder if it doesn't exist
if (-not (Test-Path $Path)) {
    New-Item -Path $Path -ItemType Directory | Out-Null
    Write-Host "Created folder: $Path" -ForegroundColor Green
} else {
    Write-Host "Folder already exists: $Path" -ForegroundColor Yellow
}

# Share the folder
if (Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue) {
    Write-Host "Share '$ShareName' already exists. Re-configuring..." -ForegroundColor Yellow
    Remove-SmbShare -Name $ShareName -Force
}

New-SmbShare -Name $ShareName -Path $Path -FullAccess $Username -Description "SandStories IPAs for iPhone" | Out-Null
Write-Host "Successfully shared '$Path' as '$ShareName' on the network!" -ForegroundColor Green

# Get local IP addresses to display
Write-Host "`nTo connect from your iPhone:" -ForegroundColor Cyan
Write-Host "1. Open the Files app on your iPhone." -ForegroundColor White
Write-Host "2. Tap the (...) icon in the top right and select 'Connect to Server'." -ForegroundColor White
Write-Host "3. Enter: smb://NitroV  (or use the IP address below)" -ForegroundColor White

$ips = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -like "*Wi-Fi*" -or $_.InterfaceAlias -like "*Ethernet*" } | Select-Object -ExpandProperty IPAddress
foreach ($ip in $ips) {
    Write-Host "   smb://$ip" -ForegroundColor Cyan
}

Write-Host "4. Log in as 'Registered User' with your Windows username ($Username) and Windows password." -ForegroundColor White
Write-Host "`nNote: If you use a PIN to log into Windows, you must use your actual Windows/Microsoft account password here, not the PIN." -ForegroundColor Yellow
Read-Host "`nPress Enter to exit"
