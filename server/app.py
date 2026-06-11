from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .livekit_tokens import create_livekit_token, livekit_url
from .package_validator import sha256_hex, validate_package
from .storage import extracted_dir, safe_name, uploads_dir


app = FastAPI(title="SandStories Field Console")
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

device_sockets: dict[str, WebSocket] = {}
dashboard_sockets: set[WebSocket] = set()


@app.on_event("startup")
def startup() -> None:
    db.init_db()


def operator_token() -> str:
    return os.environ.get("SANDSTORIES_OPERATOR_TOKEN", "field-console")


def device_token() -> str:
    return os.environ.get("SANDSTORIES_DEVICE_TOKEN", "field-device")


def check_operator(request: Request) -> None:
    expected = operator_token()
    supplied = request.headers.get("X-SandStories-Token") or request.query_params.get("token")
    if expected and supplied != expected:
        raise HTTPException(status_code=401, detail="invalid operator token")


def check_device_token(supplied: str | None) -> None:
    expected = device_token()
    if expected and supplied != expected:
        raise HTTPException(status_code=401, detail="invalid device token")


async def broadcast_dashboard(message: dict[str, Any]) -> None:
    stale: list[WebSocket] = []
    for ws in dashboard_sockets:
        try:
            await ws.send_json(message)
        except Exception:
            stale.append(ws)
    for ws in stale:
        dashboard_sockets.discard(ws)


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return (BASE_DIR / "static" / "dashboard.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "time": time.time(), "livekitUrl": livekit_url()}


@app.post("/api/devices/register")
async def register_device(payload: dict[str, Any], x_sandstories_token: str | None = Header(default=None)) -> dict[str, Any]:
    check_device_token(x_sandstories_token)
    device_id = str(payload.get("deviceId") or uuid.uuid4())
    name = str(payload.get("name") or device_id)
    db.upsert_device(device_id, name, "online", json.dumps(payload, separators=(",", ":")))
    await broadcast_dashboard({"type": "devices_changed"})
    return {"ok": True, "deviceId": device_id}


@app.get("/api/devices")
def devices(request: Request) -> list[dict[str, Any]]:
    check_operator(request)
    rows = db.list_devices()
    online = set(device_sockets.keys())
    for row in rows:
        row["connected"] = row["id"] in online
    return rows


@app.post("/api/devices/{device_id}/commands")
async def create_command(device_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    check_operator(request)
    command_id = str(uuid.uuid4())
    command_type = str(payload.get("type") or "ping")
    message = {"type": "command", "commandId": command_id, "name": command_type, "payload": payload.get("payload", {})}
    ws = device_sockets.get(device_id)
    if not ws:
        raise HTTPException(status_code=409, detail="device is not connected")
    await ws.send_json(message)
    await broadcast_dashboard({"type": "command_sent", "deviceId": device_id, "command": message})
    return {"ok": True, "commandId": command_id}


@app.websocket("/ws/device/{device_id}")
async def ws_device(websocket: WebSocket, device_id: str) -> None:
    token = websocket.query_params.get("token")
    if token != device_token():
        await websocket.close(code=1008)
        return
    await websocket.accept()
    device_sockets[device_id] = websocket
    db.upsert_device(device_id, websocket.query_params.get("name") or device_id, "online")
    await broadcast_dashboard({"type": "devices_changed"})
    try:
        while True:
            msg = await websocket.receive_json()
            db.upsert_device(device_id, str(msg.get("deviceName") or device_id), "online", json.dumps(msg, separators=(",", ":")))
            await broadcast_dashboard({"type": "device_message", "deviceId": device_id, "message": msg})
    except WebSocketDisconnect:
        pass
    finally:
        if device_sockets.get(device_id) is websocket:
            device_sockets.pop(device_id, None)
        db.upsert_device(device_id, device_id, "offline")
        await broadcast_dashboard({"type": "devices_changed"})


@app.websocket("/ws/dashboard")
async def ws_dashboard(websocket: WebSocket) -> None:
    if websocket.query_params.get("token") != operator_token():
        await websocket.close(code=1008)
        return
    await websocket.accept()
    dashboard_sockets.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        dashboard_sockets.discard(websocket)


@app.get("/api/livekit/token")
def livekit_token(request: Request, room: str, identity: str, role: str = "viewer") -> dict[str, Any]:
    supplied = request.headers.get("X-SandStories-Token") or request.query_params.get("token")
    if role == "device":
        check_device_token(supplied)
        can_publish, can_subscribe = True, False
    else:
        check_operator(request)
        can_publish, can_subscribe = False, True
    return {
        "url": livekit_url(),
        "token": create_livekit_token(room=room, identity=identity, can_publish=can_publish, can_subscribe=can_subscribe),
        "room": room,
    }


@app.post("/upload")
async def upload_legacy(
    request: Request,
    x_sandstories_filename: str | None = Header(default=None),
    x_sandstories_session_id: str | None = Header(default=None),
    x_sandstories_sha256: str | None = Header(default=None),
    x_sandstories_token: str | None = Header(default=None),
) -> JSONResponse:
    check_device_token(x_sandstories_token or request.query_params.get("token"))
    filename = x_sandstories_filename or "sandstories_session.zip"
    package_id = str(uuid.uuid4())
    stored_name = f"{int(time.time())}_{package_id}_{safe_name(filename)}"
    if not stored_name.endswith(".zip"):
        stored_name += ".zip"
    final_path = uploads_dir() / stored_name
    part_path = final_path.with_suffix(final_path.suffix + ".part")

    with part_path.open("wb") as out:
        async for chunk in request.stream():
            out.write(chunk)
    part_path.replace(final_path)

    actual_sha = sha256_hex(final_path)
    validation_extract_dir = extracted_dir() / package_id
    report = validate_package(final_path, validation_extract_dir, expected_zip_sha256=x_sandstories_sha256)
    report_path = validation_extract_dir / "validation_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    summary = report.get("summary", {})
    session_id = x_sandstories_session_id or summary.get("sessionId")
    db.insert_package(
        {
            "id": package_id,
            "session_id": session_id,
            "device_id": request.headers.get("X-SandStories-Device-Id"),
            "filename": filename,
            "zip_path": str(final_path),
            "extracted_path": str(validation_extract_dir),
            "size_bytes": final_path.stat().st_size,
            "sha256": actual_sha,
            "uploaded_at": time.time(),
            "validation_status": report["status"],
            "validation_report_path": str(report_path),
            "frame_count": summary.get("depthFrames"),
            "duration_seconds": summary.get("durationSeconds"),
        }
    )
    await broadcast_dashboard({"type": "packages_changed"})
    return JSONResponse(
        status_code=201 if report["status"] == "valid" else 422,
        content={
            "ok": report["status"] == "valid",
            "packageId": package_id,
            "sessionId": session_id,
            "validationStatus": report["status"],
            "downloadUrl": f"/api/packages/{package_id}/download",
            "report": report,
        },
    )


@app.get("/api/packages")
def packages(request: Request) -> list[dict[str, Any]]:
    check_operator(request)
    return db.list_packages()


@app.get("/api/packages/{package_id}")
def package_detail(package_id: str, request: Request) -> dict[str, Any]:
    check_operator(request)
    package = db.get_package(package_id)
    if not package:
        raise HTTPException(status_code=404, detail="package not found")
    return package


@app.get("/api/packages/{package_id}/validation")
def package_validation(package_id: str, request: Request) -> Any:
    check_operator(request)
    package = db.get_package(package_id)
    if not package or not package.get("validation_report_path"):
        raise HTTPException(status_code=404, detail="validation report not found")
    return json.loads(Path(package["validation_report_path"]).read_text(encoding="utf-8"))


@app.get("/api/packages/{package_id}/download")
def package_download(package_id: str, request: Request) -> FileResponse:
    check_operator(request)
    package = db.get_package(package_id)
    if not package:
        raise HTTPException(status_code=404, detail="package not found")
    path = Path(package["zip_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="zip not found")
    return FileResponse(path, filename=package["filename"], media_type="application/zip")
