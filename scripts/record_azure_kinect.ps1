[CmdletBinding()]
param(
    [ValidateRange(1, 3600)]
    [int]$DurationSeconds = 90,

    [string]$OutputRoot = "$env:USERPROFILE\Documents\SandStories\AzureKinectSessions",
    [string]$SessionId,

    [ValidateSet("NFOV_2X2BINNED", "NFOV_UNBINNED", "WFOV_2X2BINNED", "WFOV_UNBINNED", "PASSIVE_IR")]
    [string]$DepthMode = "NFOV_UNBINNED",

    [ValidateSet("720p", "1080p", "1440p", "1536p", "2160p", "3072p")]
    [string]$ColorMode = "1080p",

    [ValidateSet(5, 15, 30)]
    [int]$FramesPerSecond = 30,

    [ValidateRange(20, 300)]
    [int]$SensorHeightCm = 80,

    [ValidateSet("indoor", "shade", "direct_sun", "overcast")]
    [string]$Lighting = "indoor",

    [ValidateSet("dry", "wet")]
    [string]$SurfaceType = "dry",

    [ValidateRange(1, 99)]
    [int]$Replicate = 1,

    [ValidateRange(0, 60)]
    [double]$BaselineSeconds = 3.0,

    [string]$AudioDevice = "Microphone Array (Azure Kinect Microphone Array)",
    [switch]$SkipAudio,
    [switch]$SkipConversion,
    [switch]$PrepareGodot,
    [string]$RecorderPath,
    [string]$Python = "python",
    [string]$FFmpeg = "ffmpeg",
    [string]$FFprobe = "ffprobe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-AzureKinectRecorder {
    param([string]$ExplicitPath)
    if ($ExplicitPath) {
        if (Test-Path -LiteralPath $ExplicitPath -PathType Leaf) {
            return (Resolve-Path -LiteralPath $ExplicitPath).Path
        }
        throw "k4arecorder was not found at: $ExplicitPath"
    }
    $command = Get-Command k4arecorder -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    foreach ($candidate in @(
        "C:\Program Files\Azure Kinect SDK v1.4.2\tools\k4arecorder.exe",
        "C:\Program Files\Azure Kinect SDK v1.4.1\tools\k4arecorder.exe",
        "C:\Program Files\Azure Kinect SDK\tools\k4arecorder.exe"
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    throw "Azure Kinect SDK recorder was not found. Install Sensor SDK 1.4.2 first."
}

$recorder = Resolve-AzureKinectRecorder -ExplicitPath $RecorderPath
$ffmpegCommand = Get-Command $FFmpeg -ErrorAction SilentlyContinue
$ffprobeCommand = Get-Command $FFprobe -ErrorAction SilentlyContinue
$pythonCommand = Get-Command $Python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    throw "Python was not found: $Python"
}
if (-not $SkipAudio -and -not $ffmpegCommand) {
    throw "ffmpeg was not found. It is required to record microphone audio."
}
if (-not $SkipConversion -and -not $ffmpegCommand) {
    throw "ffmpeg was not found. It is required to encode depth-aligned RGB."
}
if (-not $SkipConversion -and -not $ffprobeCommand) {
    throw "ffprobe was not found. It is required to validate microphone duration."
}

$previousErrorPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $deviceOutput = @(& $recorder --list 2>&1 | ForEach-Object { $_.ToString() })
    $deviceExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousErrorPreference
}
$deviceText = $deviceOutput -join "`n"
if ($deviceExitCode -ne 0 -or $deviceText -match "(?i)(no\s+(connected\s+)?devices?|0\s+(connected\s+)?devices?)") {
    throw "No Azure Kinect DK is available. Check external power, USB 3 and k4aviewer. Output: $($deviceOutput -join ' | ')"
}

if (-not $SessionId) {
    $SessionId = "azure_kinect_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
}
$sessionDir = Join-Path $OutputRoot "session_$SessionId"
if (Test-Path -LiteralPath $sessionDir) {
    throw "Session folder already exists; choose a different -SessionId: $sessionDir"
}
$sourceDir = Join-Path $sessionDir "source"
New-Item -ItemType Directory -Path $sourceDir -Force | Out-Null
$mkvPath = Join-Path $sourceDir "azure_kinect.mkv"
$audioPath = Join-Path $sessionDir "audio.wav"
$metadataPath = Join-Path $sessionDir "recording_metadata.json"
$conditionsPath = Join-Path $sessionDir "conditions.json"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

$conditions = [ordered]@{
    sensorHeightCm = $SensorHeightCm
    lighting = $Lighting
    surfaceType = $SurfaceType
    replicate = $Replicate
}
[System.IO.File]::WriteAllText($conditionsPath, ($conditions | ConvertTo-Json), $utf8NoBom)

$audioProcess = $null
$audioStartedUtc = $null
if (-not $SkipAudio) {
    $audioStartedUtc = (Get-Date).ToUniversalTime()
    $audioInput = 'audio="{0}"' -f $AudioDevice.Replace('"', '\"')
    $audioArguments = @(
        "-y", "-hide_banner", "-loglevel", "error",
        "-f", "dshow", "-i", $audioInput,
        "-t", $DurationSeconds,
        "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le",
        ('"{0}"' -f $audioPath)
    )
    $audioProcess = Start-Process -FilePath $ffmpegCommand.Source -ArgumentList $audioArguments -PassThru -WindowStyle Hidden
    Start-Sleep -Milliseconds 250
}

$kinectStartedUtc = (Get-Date).ToUniversalTime()
$kinectArguments = @(
    "-l", $DurationSeconds,
    "-c", $ColorMode,
    "-d", $DepthMode,
    "-r", $FramesPerSecond,
    ('"{0}"' -f $mkvPath)
)
Write-Host "Recording Azure Kinect session $SessionId for $DurationSeconds seconds..."
Write-Host "Keep the sand untouched for the first $BaselineSeconds seconds (baseline phase), then make one visible and audible clap near the start for synchronization."
$kinectProcess = Start-Process -FilePath $recorder -ArgumentList $kinectArguments -PassThru -WindowStyle Hidden
$kinectProcess.WaitForExit()
if ($audioProcess) {
    $audioProcess.WaitForExit()
}
$endedUtc = (Get-Date).ToUniversalTime()

$metadata = [ordered]@{
    schemaVersion = 1
    sessionId = $SessionId
    deviceModel = "Azure Kinect DK"
    kinectStartedUtc = $kinectStartedUtc.ToString("o")
    audioStartedUtc = if ($audioStartedUtc) { $audioStartedUtc.ToString("o") } else { $null }
    endedUtc = $endedUtc.ToString("o")
    durationRequestedSeconds = $DurationSeconds
    depthMode = $DepthMode
    colorMode = $ColorMode
    framesPerSecond = $FramesPerSecond
    audioDevice = if ($SkipAudio) { $null } else { $AudioDevice }
    audioSampleRate = if ($SkipAudio) { $null } else { 48000 }
    audioChannels = if ($SkipAudio) { $null } else { 1 }
    k4aRecorderPath = $recorder
    k4aExitCode = $kinectProcess.ExitCode
    audioExitCode = if ($audioProcess) { $audioProcess.ExitCode } else { $null }
    osVersion = [System.Environment]::OSVersion.VersionString
}
[System.IO.File]::WriteAllText($metadataPath, ($metadata | ConvertTo-Json -Depth 5), $utf8NoBom)

if ($kinectProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $mkvPath -PathType Leaf) -or (Get-Item -LiteralPath $mkvPath).Length -eq 0) {
    throw "Azure Kinect recording failed with exit code $($kinectProcess.ExitCode). Metadata: $metadataPath"
}
if ($audioProcess -and ($audioProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $audioPath -PathType Leaf))) {
    throw "Microphone recording failed. Run azure_kinect_preflight.ps1 -ListAudioDevices and pass the exact -AudioDevice name."
}

if (-not $SkipConversion) {
    $converter = Join-Path $PSScriptRoot "convert_azure_kinect_mkv.py"
    $convertArguments = @(
        $converter,
        $mkvPath,
        "--session-dir", $sessionDir,
        "--session-id", $SessionId,
        "--recording-metadata", $metadataPath,
        "--fps", $FramesPerSecond,
        "--sensor-height-cm", $SensorHeightCm,
        "--lighting", $Lighting,
        "--surface-type", $SurfaceType,
        "--replicate", $Replicate,
        "--ffmpeg", $(if ($ffmpegCommand) { $ffmpegCommand.Source } else { $FFmpeg }),
        "--ffprobe", $(if ($ffprobeCommand) { $ffprobeCommand.Source } else { $FFprobe }),
        "--baseline-seconds", $BaselineSeconds,
        "--no-copy-source"
    )
    if (-not $SkipAudio) {
        $convertArguments += @("--audio", $audioPath)
    }
    & $Python @convertArguments
    if ($LASTEXITCODE -ne 0) {
        throw "MKV conversion failed. The raw recording is safe at: $mkvPath"
    }

    $evaluator = Join-Path $PSScriptRoot "evaluate_session.py"
    $evaluationDir = Join-Path $sessionDir "derived\evaluation"
    & $Python $evaluator $sessionDir --output-dir $evaluationDir
    if ($LASTEXITCODE -ne 0) {
        throw "Session conversion succeeded but evaluation failed: $sessionDir"
    }

    if ($PrepareGodot) {
        $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
        $godotProject = Join-Path $projectRoot "Godot"
        $adapter = Join-Path $godotProject "tools\prepare_production_session.py"
        & $Python $adapter $sessionDir --project $godotProject
        if ($LASTEXITCODE -ne 0) {
            throw "Godot preparation failed after a successful canonical conversion."
        }
    }
}

Write-Host "`nAzure Kinect session complete:"
Write-Host $sessionDir
Write-Host "Raw MKV: $mkvPath"
if (-not $SkipAudio) { Write-Host "Audio: $audioPath" }
if (-not $SkipConversion) { Write-Host "Manifest: $(Join-Path $sessionDir 'manifest.json')" }
