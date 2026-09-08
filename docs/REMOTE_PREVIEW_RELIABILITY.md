# Remote console and preview repair

Base: `origin/main` at `98244ab`. Changes are local; the hosted service has not been deployed or reconfigured.

## Confirmed source issues

- `server/livekit_tokens.py` and Compose used `secret` as the signing default while `deploy/livekit.yaml` used a different development secret. Defaults now agree. Existing `LIVEKIT_API_SECRET` overrides must still agree with the LiveKit server's key configuration.
- Loopback defaults could direct the iPhone/browser back to itself. iOS rejects these addresses; the token endpoint returns an actionable 503 for an invalid/loopback LiveKit URL. LAN Compose now requires `LAN_IP` explicitly. Do not run the LAN configuration unchanged as an internet deployment.
- Command routes accepted arbitrary names/parameters. They now validate all seven command types, report disconnected delivery, and forward `recordAudio` as a Boolean for start.
- ACK/results overwrote the stored device snapshot, and the dashboard let other devices or ACKs overwrite the selected capture state. Both paths are corrected; an old socket closing cannot mark its replacement offline.
- The browser SDK dependency was unversioned. It is pinned to 2.22.2 (CDN still requires connectivity).

## Hosted service: sandcapture.xwx.ac

The homepage, `/api/health`, and `/static/dashboard.js` returned HTTP 403 from this development environment. We could not inspect the running configuration or verify preview. This is an access result, not proof that the service is down.

Deploy the changed `server/app.py`, `server/livekit_tokens.py`, `server/static/dashboard.js`, and `server/static/dashboard.html` together. No database migration is required. Deployment/configuration has not been performed in this task.

For this HTTPS console:

1. Set the phone's console URL to `https://sandcapture.xwx.ac` and use the actual device token. Do not replace production credentials with the checked-in development defaults.
2. `LIVEKIT_URL` must be an externally reachable **wss://** endpoint with a valid certificate. A working HTTPS console alone does not provide LiveKit signaling or WebRTC media connectivity.
3. Match the token issuer's `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` to LiveKit's configured keys. If deploying custom keys, update LiveKit configuration as well as the field console environment.
4. Configure the reverse proxy for device/dashboard WebSockets and the chosen LiveKit signaling endpoint. Verify advertised ICE addresses and reachable media ports/TURN for the deployment; a localhost or private-only candidate will not serve a remote phone.
5. If upload has no custom destination, remote Upload Last uses this console's `/upload` and device token. Explicit custom upload URLs are preserved. Automatic upload retains its separate explicit settings.

## Client fixes and performance

- One cancellable socket loop and heartbeat, generation guards on stale callbacks, serial command execution, and bounded duplicate-ID result replay.
- Changing URL/token/device name/preview switch reconnects after a short debounce. Background/disappearance stops networking; foreground reconnects. Thermal suspension cannot be undone by a late connection result.
- Start is guarded against concurrent initialization and awaits stream configuration. Stop reports observed stream/video/manifest failures; invalid-state commands and upload errors return failed. `accepted` means received, while `completed` reflects the operation result.
- Preview is bounded to 640x480 at 10 fps with simulcast off, and no frames are fed while there are no remote participants. Full-resolution capture files are unaffected.
- Idle AR no longer requests raw/smoothed depth frame semantics. Recording restores the original full-quality semantics; optional mesh visualization remains intentional.
- Tray scanning moved off the main actor; disabled motion filtering skips its unused conversion and reduction.
- Raw depth conversion, statistics, RGB encoding, Vision gesture tracking, disk writing, and AR rendering still cost energy. These changes do not establish which component dominates on a specific phone. No measured battery/temperature/FPS improvement is claimed.

## Verification

Automated backend tests use simulated device WebSockets; they do not execute ARKit:

```sh
python -m pytest tests/test_remote_console.py -q
node --test tests/remote_dashboard.test.cjs
node --check server/static/dashboard.js
```

All 20 backend and 3 dashboard tests passed at implementation time. Swift syntax was inspected with a parser against the baseline; it is not a Swift typecheck. The current Windows/WSL environment has no Swift/xtool/Apple SDK, so an iOS build and physical-device acceptance remain required.

On an iPhone, verify: connect with actual hosted credentials; preview joins/leaves and phone rotation; start (with and without audio), pause, resume, mark, stop/save, and upload; verify manifest/streams and server validation; repeat disconnect/reconnect and settings changes; confirm remote off stays off. Test with two dashboard devices so one cannot overwrite the other's status. Test failed storage/upload to confirm failed results. The duplicate-result cache covers 128 IDs during this manager's lifetime and is not persisted across process restarts.

Compare identical fixed-rig recordings for 10 minutes with preview off, viewer connected, and viewer disconnected. Keep ambient temperature, screen brightness, power source, device, and recording settings fixed. Record thermal state, battery delta, saved-frame retention, UI responsiveness, and Instruments Energy/Time Profiler on macOS. Check actual recording quality and synchronization before accepting the performance changes.
