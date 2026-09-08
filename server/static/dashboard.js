const token = new URLSearchParams(location.search).get('token') || localStorage.getItem('sandstoriesToken') || 'field-console';
localStorage.setItem('sandstoriesToken', token);

let devices = [];
let selectedDeviceId = null;
let livekitRoom = null;
let previewSocket = null;
let previewGeneration = 0;
let previewImageURL = null;
const previewImageURLs = new Set();
let previewReconnectTimer = null;

const qs = (s) => document.querySelector(s);
const log = (msg, data) => {
  const line = `[${new Date().toLocaleTimeString()}] ${msg}${data ? ' ' + JSON.stringify(data) : ''}\n`;
  qs('#events').textContent = (line + qs('#events').textContent).slice(0, 24000);
};

function headers() { return { 'X-SandStories-Token': token }; }
function fmtBytes(n) {
  if (!n) return '--';
  const units = ['B', 'KB', 'MB', 'GB'];
  let v = Number(n); let i = 0;
  while (v > 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i ? 1 : 0)} ${units[i]}`;
}

function completionStatusClass(status) {
  if (status === 'completed') return 'status-valid';
  if (status === 'failed' || status === 'unavailable') return 'status-invalid';
  return 'status-other';
}

async function api(path, options = {}) {
  const res = await fetch(path, { ...options, headers: { ...headers(), ...(options.headers || {}) } });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

async function refreshDevices() {
  devices = await api('/api/devices');
  const select = qs('#device-select');
  select.innerHTML = '';
  for (const d of devices) {
    const opt = document.createElement('option');
    opt.value = d.id;
    opt.textContent = `${d.connected ? '●' : '○'} ${d.name || d.id}`;
    select.appendChild(opt);
  }
  if (!selectedDeviceId && devices.length) selectedDeviceId = devices[0].id;
  if (selectedDeviceId) select.value = selectedDeviceId;
  const connected = devices.some(d => d.connected);
  qs('#device-status').textContent = connected ? 'DEVICE ONLINE' : 'NO DEVICE';
  qs('#device-status').className = connected ? 'pill ok' : 'pill off';
}

async function refreshPackages() {
  const rows = await api('/api/packages');
  const body = qs('#packages-body');
  body.innerHTML = '';
  for (const p of rows) {
    const tr = document.createElement('tr');
    const statusClass = p.validation_status === 'valid' ? 'status-valid' : (p.validation_status === 'invalid' ? 'status-invalid' : 'status-other');
    const completionStatus = p.completion_status || 'disabled';
    const completionClass = completionStatusClass(completionStatus);
    const completionActions = completionStatus === 'completed'
      ? `<button class="secondary" onclick="showCompletion('${p.id}')">AI Report</button>
         <button class="secondary" onclick="downloadCompletion('${p.id}')">AI ZIP</button>`
      : ((completionStatus === 'failed' || completionStatus === 'unavailable')
        ? `<button class="secondary" onclick="retryCompletion('${p.id}')">Retry AI</button>`
        : '');
    tr.innerHTML = `
      <td class="${statusClass}">${p.validation_status.toUpperCase()}</td>
      <td>${p.session_id || p.filename}</td>
      <td>${p.frame_count ?? '--'}</td>
      <td>${fmtBytes(p.size_bytes)}</td>
      <td class="${completionClass}" data-completion-status>${completionStatus.toUpperCase()}</td>
      <td>${new Date(p.uploaded_at * 1000).toLocaleString()}</td>
      <td>
        <button class="secondary" onclick="downloadPackage('${p.id}')">Download</button>
        <button class="secondary" onclick="showValidation('${p.id}')">Report</button>
        ${completionActions}
      </td>`;
    tr.querySelector('[data-completion-status]').title = p.completion_error || '';
    body.appendChild(tr);
  }
}

window.downloadPackage = (id) => {
  location.href = `/api/packages/${id}/download?token=${encodeURIComponent(token)}`;
};

window.showValidation = async (id) => {
  const report = await api(`/api/packages/${id}/validation`);
  log('validation_report', report);
};

window.downloadCompletion = (id) => {
  location.href = `/api/packages/${id}/completion/download?token=${encodeURIComponent(token)}`;
};

window.showCompletion = async (id) => {
  const report = await api(`/api/packages/${id}/completion`);
  log('any2full_quality_report', report);
};

window.retryCompletion = async (id) => {
  try {
    const result = await api(`/api/packages/${id}/completion/retry`, { method: 'POST' });
    log('completion queued', result);
    await refreshPackages();
  } catch (error) {
    log('completion retry failed', { error: String(error) });
  }
};

async function sendCommand(type) {
  if (!selectedDeviceId) return log('no device selected');
  const result = await api(`/api/devices/${selectedDeviceId}/commands`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type, payload: {} }),
  });
  log('command sent', result);
}

function disconnectPreview() {
  previewGeneration++;
  clearTimeout(previewReconnectTimer);
  previewReconnectTimer = null;
  if (previewSocket) { previewSocket.onclose = null; previewSocket.close(); previewSocket = null; }
  if (livekitRoom) { livekitRoom.disconnect(); livekitRoom = null; }
  for (const url of previewImageURLs) URL.revokeObjectURL(url);
  previewImageURLs.clear();
  previewImageURL = null;
  qs('#preview').innerHTML = '';
  qs('#preview-status').textContent = 'Preview off';
}

async function connectPreview() {
  disconnectPreview();
  if (!selectedDeviceId) return log('no device selected');
  const generation = previewGeneration;
  const deviceId = selectedDeviceId;
  if (qs('#preview-transport').value !== 'liveKit') {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws/preview/viewer/${encodeURIComponent(deviceId)}?token=${encodeURIComponent(token)}`);
    previewSocket = ws;
    ws.binaryType = 'blob';
    const picture = document.createElement('img');
    picture.alt = 'Live iPhone preview';
    picture.style = 'width:100%;height:100%;object-fit:contain';
    qs('#preview').appendChild(picture);
    qs('#preview-status').textContent = 'Connecting to Console Tunnel…';
    ws.onopen = () => {
      if (generation !== previewGeneration) return;
      qs('#preview-status').textContent = 'Waiting for iPhone preview…';
      ws.send('ready');
    };
    ws.onmessage = (event) => {
      if (generation !== previewGeneration) return;
      if (typeof event.data === 'string') {
        qs('#preview-status').textContent = 'Waiting for iPhone; enable Console Tunnel preview in the app';
        ws.send('ready');
        return;
      }
      const url = URL.createObjectURL(event.data);
      previewImageURLs.add(url);
      const previous = previewImageURL;
      previewImageURL = url;
      const complete = () => {
        if (previous) { URL.revokeObjectURL(previous); previewImageURLs.delete(previous); }
        if (generation === previewGeneration && ws.readyState === WebSocket.OPEN) ws.send('ready');
      };
      picture.onload = () => {
        if (generation === previewGeneration) qs('#preview-status').textContent = 'Console Tunnel live';
        complete();
      };
      picture.onerror = () => {
        if (generation === previewGeneration) qs('#preview-status').textContent = 'Preview frame could not be decoded';
        complete();
      };
      picture.src = url;
    };
    ws.onclose = () => {
      if (generation !== previewGeneration) return;
      qs('#preview-status').textContent = 'Preview disconnected; retrying…';
      previewReconnectTimer = setTimeout(() => {
        if (generation === previewGeneration) connectPreview().catch(err => log('preview failed', { error: String(err) }));
      }, 2000);
    };
    return;
  }
  if (!window.LivekitClient) throw new Error('LiveKit client unavailable');
  qs('#preview-status').textContent = 'Connecting to LiveKit…';
  const roomName = `device_${deviceId}`;
  const cfg = await api(`/api/livekit/token?room=${encodeURIComponent(roomName)}&identity=dashboard_${Date.now()}&role=viewer`);
  if (generation !== previewGeneration) return;
  if (location.protocol === 'https:' && !cfg.url.startsWith('wss://')) {
    throw new Error('HTTPS console requires a reachable wss:// LIVEKIT_URL on the server');
  }
  const room = new LivekitClient.Room();
  livekitRoom = room;
  room.on(LivekitClient.RoomEvent.TrackSubscribed, (track) => {
    if (generation === previewGeneration && track.kind === LivekitClient.Track.Kind.Video) {
      qs('#preview').innerHTML = '';
      qs('#preview').appendChild(track.attach());
      qs('#preview-status').textContent = 'LiveKit live';
    }
  });
  try { await room.connect(cfg.url, cfg.token); }
  catch (error) { await room.disconnect(); throw error; }
  if (generation !== previewGeneration) { await room.disconnect(); return; }
  log('preview connected', { room: roomName });
}

function connectDashboardSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/dashboard?token=${encodeURIComponent(token)}`);
  ws.onopen = () => { qs('#server-status').textContent = 'SERVER ONLINE'; qs('#server-status').className = 'pill ok'; };
  ws.onclose = () => { qs('#server-status').textContent = 'SERVER OFFLINE'; qs('#server-status').className = 'pill off'; setTimeout(connectDashboardSocket, 1500); };
  ws.onmessage = async (event) => {
    const msg = JSON.parse(event.data);
    log(msg.type, msg);
    if (msg.type === 'devices_changed') await refreshDevices();
    if (msg.type === 'packages_changed') await refreshPackages();
    if (msg.type === 'completion_changed') await refreshPackages();
    if (msg.type === 'device_message' && msg.deviceId === selectedDeviceId && msg.message?.type === 'device_status') {
      const m = msg.message || {};
      qs('#capture-state').textContent = m.saving ? 'saving' : m.starting ? 'starting' : m.paused ? 'paused' : m.recording ? 'recording' : 'ready';
      qs('#elapsed').textContent = m.elapsedSeconds != null ? `${Math.round(m.elapsedSeconds)}s` : '--';
      qs('#frames').textContent = m.savedFrames ?? '--';
      qs('#upload-state').textContent = m.uploadStatus || '--';
    }
  };
}

qs('#device-select').addEventListener('change', (e) => { disconnectPreview(); selectedDeviceId = e.target.value; });
document.querySelectorAll('[data-command]').forEach(btn => btn.addEventListener('click', () => sendCommand(btn.dataset.command).catch(err => log('command failed', { error: String(err) }))));
qs('#refresh').addEventListener('click', async () => { await refreshDevices(); await refreshPackages(); });
qs('#connect-preview').addEventListener('click', () => connectPreview().catch(err => log('preview failed', { error: String(err) })));

setInterval(() => { qs('#clock').textContent = new Date().toLocaleTimeString(); }, 1000);
refreshDevices().catch(err => log('devices error', { error: String(err) }));
refreshPackages().catch(err => log('packages error', { error: String(err) }));
connectDashboardSocket();

qs('#disconnect-preview').addEventListener('click', disconnectPreview);
qs('#preview-transport').addEventListener('change', disconnectPreview);
document.addEventListener('visibilitychange', () => { if (document.hidden) disconnectPreview(); });
