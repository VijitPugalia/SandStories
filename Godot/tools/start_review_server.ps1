param(
    [int]$Port = 8845,
    [string]$BindAddress = "127.0.0.1",
    [string]$DynamicSessionsDir = "",
    [string]$ExperimentDataDir = "",
    [string]$SessionName = "",
    [switch]$AllowConditionOverride,
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
if (-not $ExperimentDataDir) {
    $ExperimentDataDir = Join-Path (Split-Path $ProjectDir -Parent) "server_data\experiments"
}
New-Item -ItemType Directory -Force -Path $ExperimentDataDir | Out-Null
$ExperimentDataDir = (Resolve-Path -LiteralPath $ExperimentDataDir).Path

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
    $DynamicSessionsDir,
    $ExperimentDataDir
)

Write-Host ""
Write-Host "SandStories review server"
Write-Host "  Root:       $BaseUrl/"
if ($SessionName) {
    $SessionUrl = "$BaseUrl/assets/processed_sessions/$SessionName/session.json"
    $EncodedSessionUrl = [Uri]::EscapeDataString($SessionUrl)
    Write-Host "  Session:    $BaseUrl/index.html?session=$EncodedSessionUrl&autoplay=0"
}
Write-Host "  Study host: $BaseUrl/experiment_host.html"
Write-Host "  Stage 1:    $BaseUrl/experiment_host.html?stage=stage1&participant=qa001"
if ($AllowConditionOverride) {
    Write-Host "  Stage 1 QA: $BaseUrl/experiment_host.html?stage=stage1&participant=qa001&condition=no_gestures&researcher=1"
}
Write-Host "  Stage 2:    $BaseUrl/experiment_host.html?stage=stage2&participant=qa201"
if ($DynamicSessionsDir) {
    Write-Host "  Sessions:   $DynamicSessionsDir"
}
Write-Host "  Responses:  $ExperimentDataDir"
if ($AllowConditionOverride) {
    Write-Host "  QA override: condition overrides and pilot runs enabled"
}
Write-Host ""

$env:SANDSTORIES_ALLOW_CONDITION_OVERRIDE = if ($AllowConditionOverride) { "1" } else { "0" }

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
