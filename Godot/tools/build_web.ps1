param(
    [string]$GodotExe = "C:\Users\lj200\Documents\Tools\Godot_v4.5.1-stable_mono_win64\Godot_v4.5.1-stable_win64_console.exe",
    [string]$ProjectDir = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$TemplateZip = "C:\Users\lj200\AppData\Roaming\Godot\export_templates\4.5.1.stable\web_nothreads_release.zip"
)

$ErrorActionPreference = "Stop"

$BuildDir = Join-Path $ProjectDir "build\web"
$TempDir = Join-Path $env:TEMP "sandstories_godot_web_template"

New-Item -ItemType Directory -Force $BuildDir | Out-Null

& $GodotExe --headless --path $ProjectDir --export-pack Web "build/web/index.pck"
if ($LASTEXITCODE -ne 0) {
    throw "Godot pack export failed with exit code $LASTEXITCODE"
}

if (Test-Path $TempDir) {
    Remove-Item -LiteralPath $TempDir -Recurse -Force
}
New-Item -ItemType Directory -Force $TempDir | Out-Null
Expand-Archive -LiteralPath $TemplateZip -DestinationPath $TempDir -Force

Copy-Item -LiteralPath (Join-Path $TempDir "godot.js") -Destination (Join-Path $BuildDir "index.js") -Force
Copy-Item -LiteralPath (Join-Path $TempDir "godot.wasm") -Destination (Join-Path $BuildDir "index.wasm") -Force
Copy-Item -LiteralPath (Join-Path $TempDir "godot.audio.worklet.js") -Destination (Join-Path $BuildDir "index.audio.worklet.js") -Force
Copy-Item -LiteralPath (Join-Path $TempDir "godot.audio.position.worklet.js") -Destination (Join-Path $BuildDir "index.audio.position.worklet.js") -Force
Copy-Item -LiteralPath (Join-Path $TempDir "godot.service.worker.js") -Destination (Join-Path $BuildDir "index.service.worker.js") -Force
Copy-Item -LiteralPath (Join-Path $TempDir "godot.offline.html") -Destination (Join-Path $BuildDir "index.offline.html") -Force

$PckSize = (Get-Item (Join-Path $BuildDir "index.pck")).Length
$WasmSize = (Get-Item (Join-Path $BuildDir "index.wasm")).Length
$JsSize = (Get-Item (Join-Path $BuildDir "index.js")).Length

$Config = '{"args":[],"canvasResizePolicy":2,"executable":"index","mainPack":"index.pck","experimentalVK":false,"fileSizes":{"index.pck":' + $PckSize + ',"index.wasm":' + $WasmSize + ',"index.js":' + $JsSize + '},"focusCanvas":true,"gdextensionLibs":[],"serviceWorker":"","ensureCrossOriginIsolationHeaders":false}'

$Html = Get-Content -Raw (Join-Path $TempDir "godot.html")
$Html = $Html.Replace('$GODOT_PROJECT_NAME', 'Sand Stories Prototype')
$Html = $Html.Replace('$GODOT_SPLASH_COLOR', '#000000')
$HeadInclude = @'
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
Set-Content -LiteralPath (Join-Path $BuildDir "index.html") -Value $Html -Encoding UTF8

Get-ChildItem $BuildDir | Sort-Object Name | Select-Object Name, Length
