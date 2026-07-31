param(
    [string]$GodotExe = $env:GODOT_BIN,
    [string]$ProjectDir = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$TemplateZip = $env:GODOT_WEB_TEMPLATE
)

$ErrorActionPreference = "Stop"

$BuildDir = Join-Path $ProjectDir "build\web"
$WebSourceDir = Join-Path $ProjectDir "web"
$TempDir = Join-Path ([IO.Path]::GetTempPath()) (
    "sandstories_godot_web_template_{0}" -f [Guid]::NewGuid().ToString("N")
)

if (-not $GodotExe) {
    $GodotCommand = Get-Command godot4, godot -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $GodotCommand) {
        throw "Godot was not found. Pass -GodotExe or set GODOT_BIN."
    }
    $GodotExe = $GodotCommand.Source
}
if (-not (Test-Path -LiteralPath $GodotExe -PathType Leaf)) {
    throw "Godot executable does not exist: $GodotExe"
}

if (-not $TemplateZip) {
    $GodotVersion = (& $GodotExe --version | Select-Object -First 1).Trim()
    if ($LASTEXITCODE -ne 0 -or $GodotVersion -notmatch '^(\d+\.\d+\.\d+\.[^.]+)') {
        throw "Could not determine the Godot export-template version."
    }
    $TemplateZip = Join-Path $env:APPDATA (
        "Godot\export_templates\{0}\web_nothreads_release.zip" -f $Matches[1]
    )
}
if (-not (Test-Path -LiteralPath $TemplateZip -PathType Leaf)) {
    throw (
        "Web export template does not exist: $TemplateZip. " +
        "Install the matching Godot templates, pass -TemplateZip, or set " +
        "GODOT_WEB_TEMPLATE."
    )
}

New-Item -ItemType Directory -Force $BuildDir | Out-Null

& $GodotExe --headless --path $ProjectDir --export-pack Web "build/web/index.pck"
if ($LASTEXITCODE -ne 0) {
    throw "Godot pack export failed with exit code $LASTEXITCODE"
}

try {
    New-Item -ItemType Directory -Force $TempDir | Out-Null
    Expand-Archive -LiteralPath $TemplateZip -DestinationPath $TempDir -Force

    Copy-Item -LiteralPath (Join-Path $TempDir "godot.js") -Destination (Join-Path $BuildDir "index.js") -Force
    Copy-Item -LiteralPath (Join-Path $TempDir "godot.wasm") -Destination (Join-Path $BuildDir "index.wasm") -Force
    Copy-Item -LiteralPath (Join-Path $TempDir "godot.audio.worklet.js") -Destination (Join-Path $BuildDir "index.audio.worklet.js") -Force
    Copy-Item -LiteralPath (Join-Path $TempDir "godot.audio.position.worklet.js") -Destination (Join-Path $BuildDir "index.audio.position.worklet.js") -Force
    Copy-Item -LiteralPath (Join-Path $TempDir "godot.service.worker.js") -Destination (Join-Path $BuildDir "index.service.worker.js") -Force
    Copy-Item -LiteralPath (Join-Path $TempDir "godot.offline.html") -Destination (Join-Path $BuildDir "index.offline.html") -Force
    Copy-Item -LiteralPath (Join-Path $WebSourceDir "sandstories_bridge.js") -Destination (Join-Path $BuildDir "sandstories_bridge.js") -Force
    Copy-Item -LiteralPath (Join-Path $WebSourceDir "experiment_host.js") -Destination (Join-Path $BuildDir "experiment_host.js") -Force
    Copy-Item -LiteralPath (Join-Path $WebSourceDir "experiment_host.html") -Destination (Join-Path $BuildDir "experiment_host.html") -Force
    Copy-Item -LiteralPath (Join-Path $WebSourceDir "experiment_host.css") -Destination (Join-Path $BuildDir "experiment_host.css") -Force
    Copy-Item -LiteralPath (Join-Path $ProjectDir "data\experiment_protocol.json") -Destination (Join-Path $BuildDir "experiment_protocol.json") -Force

    $PckSize = (Get-Item (Join-Path $BuildDir "index.pck")).Length
    $WasmSize = (Get-Item (Join-Path $BuildDir "index.wasm")).Length
    $JsSize = (Get-Item (Join-Path $BuildDir "index.js")).Length

    $Config = '{"args":[],"canvasResizePolicy":2,"executable":"index","mainPack":"index.pck","experimentalVK":false,"fileSizes":{"index.pck":' + $PckSize + ',"index.wasm":' + $WasmSize + ',"index.js":' + $JsSize + '},"focusCanvas":true,"gdextensionLibs":[],"serviceWorker":"","ensureCrossOriginIsolationHeaders":false}'

    $Html = Get-Content -Raw (Join-Path $TempDir "godot.html")
    $Html = $Html.Replace('$GODOT_PROJECT_NAME', 'Sand Stories Prototype')
    $Html = $Html.Replace('$GODOT_SPLASH_COLOR', '#000000')
    $HeadInclude = @'
<script src="sandstories_bridge.js"></script>
<script>
window.__sandstories_log = [];
(function () {
	const debugEnabled = new URLSearchParams(location.search).get('debug') === '1';
	function writeLog(kind, text) {
		const line = `[${kind}] ${text}`;
		window.__sandstories_log.push(line);
		const existing = document.getElementById('sandstories-debug-log');
		if (existing) {
			existing.textContent = window.__sandstories_log.slice(-20).join('\n');
		}
	}
	const oldLog = console.log.bind(console);
	const oldError = console.error.bind(console);
	console.log = function (...args) {
		writeLog('log', args.map(String).join(' '));
		oldLog(...args);
	};
	console.error = function (...args) {
		writeLog('error', args.map(String).join(' '));
		oldError(...args);
	};
	window.addEventListener('error', function (event) {
		writeLog('error', event.message || event.error || 'window error');
	});
	window.addEventListener('unhandledrejection', function (event) {
		writeLog('promise', event.reason && (event.reason.stack || event.reason.message) || event.reason || 'unhandled rejection');
	});
	window.addEventListener('DOMContentLoaded', function () {
		if (!debugEnabled) {
			return;
		}
		const panel = document.createElement('pre');
		panel.id = 'sandstories-debug-log';
		panel.style.cssText = 'position:fixed;left:12px;top:12px;z-index:9999;max-width:72vw;max-height:42vh;overflow:auto;margin:0;padding:10px;background:rgba(0,0,0,.72);color:#9ff;font:12px/1.35 monospace;white-space:pre-wrap;pointer-events:none;';
		document.body.appendChild(panel);
		setTimeout(function () {
			if (!window.__sandstories_log.length) {
				writeLog('watchdog', 'No JS errors captured after 8s; likely waiting inside Godot runtime or WebGL init.');
			}
		}, 8000);
	});
}());
</script>
'@
    $Html = $Html.Replace('$GODOT_HEAD_INCLUDE', $HeadInclude)
    $Html = $Html.Replace('$GODOT_SPLASH_CLASSES', 'show-image--false fullsize--false use-filter--false')
    $Html = $Html.Replace('$GODOT_SPLASH', '')
    $Html = $Html.Replace('$GODOT_URL', 'index.js')
    $Html = $Html.Replace('$GODOT_CONFIG', $Config)
    $Html = $Html.Replace('$GODOT_THREADS_ENABLED', 'false')
    $IndexHtml = Join-Path $BuildDir "index.html"
    $HtmlWritten = $false
    for ($Attempt = 1; $Attempt -le 20; $Attempt++) {
        try {
            Set-Content -LiteralPath $IndexHtml -Value $Html -Encoding UTF8
            $HtmlWritten = $true
            break
        }
        catch [System.IO.IOException] {
            if ($Attempt -eq 20) {
                throw
            }
            Start-Sleep -Milliseconds 100
        }
    }
    if (-not $HtmlWritten) {
        throw "Failed to write Web entry point: $IndexHtml"
    }

    Get-ChildItem $BuildDir | Sort-Object Name | Select-Object Name, Length
}
finally {
    if (Test-Path -LiteralPath $TempDir) {
        Remove-Item -LiteralPath $TempDir -Recurse -Force
    }
}
