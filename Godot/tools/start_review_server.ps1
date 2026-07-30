param(
    [int]$Port = 8845,
    [string]$BindAddress = "127.0.0.1",
    [string]$DynamicSessionsDir = "",
    [string]$SessionName = "",
    [switch]$Background
)

$ErrorActionPreference = "Stop"

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WebDir = Join-Path $ProjectDir "build\web"
$ServerScript = Join-Path $PSScriptRoot "static_server.mjs"
$SandivDir = (Resolve-Path (Join-Path $ProjectDir "..\..")).Path
$NodeExe = (Get-Command node -ErrorAction Stop).Source

if (-not $DynamicSessionsDir) {
    $LocalCandidate = Join-Path $SandivDir "tmp\opencode"
    if (Test-Path -LiteralPath $LocalCandidate -PathType Container) {
        $DynamicSessionsDir = $LocalCandidate
    }
}
if ($DynamicSessionsDir) {
    $DynamicSessionsDir = (Resolve-Path -LiteralPath $DynamicSessionsDir).Path
}

if (-not (Test-Path -LiteralPath (Join-Path $WebDir "index.html") -PathType Leaf)) {
    throw "Missing Web build: $WebDir\index.html. Run tools\build_web.ps1 first."
}
if (-not (Test-Path -LiteralPath (Join-Path $WebDir "index.pck") -PathType Leaf)) {
    throw "Missing Web pack: $WebDir\index.pck. Run tools\build_web.ps1 first."
}
$Listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($Listener) {
    $OwnerIds = $Listener | Select-Object -ExpandProperty OwningProcess -Unique
    throw "Port $Port is already listening (PID: $($OwnerIds -join ', '))."
}

$BaseUrl = "http://localhost:$Port"
$ServerArgs = @(
    $ServerScript,
    $WebDir,
    [string]$Port,
    $BindAddress,
    $ProjectDir,
    $DynamicSessionsDir
)

Write-Host ""
Write-Host "SandStories review server"
Write-Host "  Root:       $BaseUrl/"
if ($SessionName) {
    $SessionUrl = "$BaseUrl/assets/processed_sessions/$SessionName/session.json"
    $EncodedSessionUrl = [Uri]::EscapeDataString($SessionUrl)
    Write-Host "  Session:    $BaseUrl/index.html?session=$EncodedSessionUrl&autoplay=0"
}
Write-Host "  Pilot:      $BaseUrl/index.html?study=pilot&participant=qa001"
Write-Host "  Stage 1 QA: $BaseUrl/index.html?study=stage1&participant=qa001&condition=no_gestures"
Write-Host "  Stage 2 QA: $BaseUrl/index.html?study=stage2&participant=qa201"
if ($DynamicSessionsDir) {
    Write-Host "  Sessions:   $DynamicSessionsDir"
}
Write-Host ""

if ($Background) {
    $LogDir = Join-Path $WebDir "diagnostics"
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $StdoutLog = Join-Path $LogDir "review_server.stdout.log"
    $StderrLog = Join-Path $LogDir "review_server.stderr.log"
    $Process = Start-Process `
        -FilePath $NodeExe `
        -ArgumentList $ServerArgs `
        -WorkingDirectory $ProjectDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdoutLog `
        -RedirectStandardError $StderrLog `
        -PassThru
    Write-Host "Started background server: PID $($Process.Id)"
    Write-Host "  stdout: $StdoutLog"
    Write-Host "  stderr: $StderrLog"
    exit 0
}

Write-Host "Press Ctrl+C to stop."
& $NodeExe @ServerArgs
exit $LASTEXITCODE
