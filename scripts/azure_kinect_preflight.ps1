[CmdletBinding()]
param(
    [string]$RecorderPath,
    [string]$ViewerPath,
    [string]$Python = "python",
    [switch]$ListAudioDevices
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-AzureKinectTool {
    param([string]$ExplicitPath, [string]$Name)
    if ($ExplicitPath) {
        if (Test-Path -LiteralPath $ExplicitPath -PathType Leaf) {
            return (Resolve-Path -LiteralPath $ExplicitPath).Path
        }
        throw "$Name was not found at: $ExplicitPath"
    }
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $candidates = @(
        "C:\Program Files\Azure Kinect SDK v1.4.2\tools\$Name.exe",
        "C:\Program Files\Azure Kinect SDK v1.4.1\tools\$Name.exe",
        "C:\Program Files\Azure Kinect SDK\tools\$Name.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    return $null
}

$recorder = Resolve-AzureKinectTool -ExplicitPath $RecorderPath -Name "k4arecorder"
$viewer = Resolve-AzureKinectTool -ExplicitPath $ViewerPath -Name "k4aviewer"
$ffmpegCommand = Get-Command ffmpeg -ErrorAction SilentlyContinue
$ffprobeCommand = Get-Command ffprobe -ErrorAction SilentlyContinue
$pythonCommand = Get-Command $Python -ErrorAction SilentlyContinue

$deviceOutput = @()
$deviceExitCode = $null
if ($recorder) {
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $deviceOutput = @(& $recorder --list 2>&1 | ForEach-Object { $_.ToString() })
        $deviceExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorPreference
    }
}
$deviceText = $deviceOutput -join "`n"
$deviceDetected = $recorder -and $deviceExitCode -eq 0 -and
    $deviceText -notmatch "(?i)(no\s+(connected\s+)?devices?|0\s+(connected\s+)?devices?)" -and
    $deviceText -match "(?i)(serial|device|index|[0-9]{6,})"

$pyk4aAvailable = $false
$pyk4aVersion = $null
if ($pythonCommand) {
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        $pyk4aVersion = (& $Python -c "import importlib.metadata; print(importlib.metadata.version('pyk4a'))" 2>$null)
        $pyk4aExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorPreference
    }
    $pyk4aAvailable = $pyk4aExitCode -eq 0
    if (-not $pyk4aAvailable) {
        $pyk4aVersion = $null
    }
}

$pnpDevices = @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
    Where-Object {
        $_.FriendlyName -match "Azure Kinect|Kinect 4K|Depth Camera" -or
        $_.InstanceId -match "VID_045E"
    } |
    Select-Object Status, Class, FriendlyName, InstanceId)

$result = [ordered]@{
    readyToRecord = [bool]($recorder -and $deviceDetected)
    readyToConvert = [bool]($pythonCommand -and $pyk4aAvailable -and $ffmpegCommand -and $ffprobeCommand)
    recorder = $recorder
    viewer = $viewer
    ffmpeg = if ($ffmpegCommand) { $ffmpegCommand.Source } else { $null }
    ffprobe = if ($ffprobeCommand) { $ffprobeCommand.Source } else { $null }
    python = if ($pythonCommand) { $pythonCommand.Source } else { $null }
    pyk4aVersion = $pyk4aVersion
    k4aListExitCode = $deviceExitCode
    k4aListOutput = $deviceOutput
    windowsDevices = $pnpDevices
}

$result | ConvertTo-Json -Depth 6

if ($ListAudioDevices -and $ffmpegCommand) {
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    Write-Host "`nDirectShow audio devices reported by ffmpeg:"
    try {
        & $ffmpegCommand.Source -hide_banner -list_devices true -f dshow -i dummy 2>&1 |
            Where-Object { $_.ToString() -match "(?i)audio|microphone|kinect" } |
            ForEach-Object { Write-Host $_.ToString() }
    } finally {
        $ErrorActionPreference = $previousErrorPreference
    }
}

if (-not $recorder) {
    [Console]::Error.WriteLine("Azure Kinect Sensor SDK recorder is not installed. Install SDK 1.4.2 first.")
    exit 2
}
if (-not $deviceDetected) {
    [Console]::Error.WriteLine("k4arecorder is installed but no Azure Kinect DK was listed. Check external power and USB 3.")
    exit 3
}
if (-not $ffmpegCommand) {
    [Console]::Error.WriteLine("ffmpeg is required for aligned RGB and microphone recording.")
    exit 4
}
if (-not $ffprobeCommand) {
    [Console]::Error.WriteLine("ffprobe is required to validate microphone duration.")
    exit 5
}
if (-not $pyk4aAvailable) {
    [Console]::Error.WriteLine("pyk4a is missing. Run: python -m pip install -r scripts/requirements-azure-kinect.txt")
    exit 6
}
