from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import uuid
from urllib.parse import urlsplit
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .any2full_worker import Any2FullConfig, run_completion
from .livekit_tokens import create_livekit_token, livekit_url
from .package_validator import sha256_hex, validate_package
from .storage import derived_dir, extracted_dir, safe_name, uploads_dir


app = FastAPI(title="SandStories Field Console")
BASE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = BASE_DIR.parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

device_sockets: dict[str, WebSocket] = {}
dashboard_sockets: set[WebSocket] = set()
completion_config: Any2FullConfig | None = None
completion_worker_task: asyncio.Task[None] | None = None


@app.on_event("startup")
async def startup() -> None:
    global completion_config, completion_worker_task
    db.init_db()
    completion_config = Any2FullConfig.from_env()
    db.reset_running_completion_jobs()
    if completion_config.enabled:
        completion_worker_task = asyncio.create_task(completion_worker_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    global completion_worker_task
    if completion_worker_task is None:
        return
    completion_worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await completion_worker_task
    completion_worker_task = None


def current_completion_config() -> Any2FullConfig:
    global completion_config
    if completion_config is None:
        completion_config = Any2FullConfig.from_env()
    return completion_config


async def completion_worker_loop() -> None:
    while True:
        package = await asyncio.to_thread(db.claim_next_completion_package)
        if package is None:
            await asyncio.sleep(1.0)
            continue
        package_id = str(package["id"])
        await broadcast_dashboard(
            {"type": "completion_changed", "packageId": package_id, "status": "running"}
        )
        try:
            result = await asyncio.to_thread(
                run_completion,
                package,
                current_completion_config(),
                REPOSITORY_ROOT,
                derived_dir(),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await asyncio.to_thread(
                db.fail_package_completion, package_id, str(exc)
            )
            status = "failed"
        else:
            await asyncio.to_thread(
                db.finish_package_completion,
                package_id,
                output_path=Path(result["outputPath"]),
                report_path=Path(result["reportPath"]),
                artifact_path=Path(result["artifactPath"]),
            )
            status = "completed"
        await broadcast_dashboard(
            {"type": "completion_changed", "packageId": package_id, "status": status}
        )


def configure_uploaded_package_completion(package_id: str, validation_status: str) -> str:
    if validation_status != "valid":
        return "disabled"
    config = current_completion_config()
    if not config.enabled:
        return "disabled"
    errors = config.readiness_errors(REPOSITORY_ROOT)
    if errors:
        db.mark_package_completion_unavailable(package_id, "; ".join(errors))
        return "unavailable"
    db.queue_package_completion(package_id)
    return "queued"


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
    return {
        "ok": True,
        "time": time.time(),
        "livekitUrl": livekit_url(),
        "any2full": current_completion_config().public_status(REPOSITORY_ROOT),
    }


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
    command_type = payload.get("type", "ping")
    allowed = {"start_recording", "stop_recording", "pause_recording", "resume_recording", "mark_segment", "upload_last_session", "ping"}
    if not isinstance(command_type, str) or command_type not in allowed:
        raise HTTPException(status_code=422, detail="unknown command")
    arguments = payload.get("payload", {})
    if not isinstance(arguments, dict):
        raise HTTPException(status_code=422, detail="payload must be an object")
    if set(arguments) - ({"recordAudio"} if command_type == "start_recording" else set()):
        raise HTTPException(status_code=422, detail="unsupported command parameters")
    if "recordAudio" in arguments and not isinstance(arguments["recordAudio"], bool):
        raise HTTPException(status_code=422, detail="recordAudio must be a boolean")
    command_id = str(uuid.uuid4())
    message = {"type": "command", "commandId": command_id, "name": command_type, "payload": payload.get("payload", {})}
    ws = device_sockets.get(device_id)
    if not ws:
        raise HTTPException(status_code=409, detail="device is not connected")
    try:
        await ws.send_json(message)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="device disconnected before command delivery") from exc
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
            if device_sockets.get(device_id) is not websocket:
                break
            if msg.get("type") == "device_status":
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
    if role not in {"device", "viewer"}:
        raise HTTPException(status_code=422, detail="invalid LiveKit role")
    if role == "device":
        check_device_token(supplied)
        can_publish, can_subscribe = True, False
    else:
        check_operator(request)
        can_publish, can_subscribe = False, True
    endpoint = urlsplit(livekit_url())
    if endpoint.scheme not in {"ws", "wss"} or not endpoint.hostname or endpoint.hostname.lower() in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        raise HTTPException(status_code=503, detail="Set LIVEKIT_URL to a ws/wss address reachable by the iPhone and browser")
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
    completion_status = configure_uploaded_package_completion(package_id, report["status"])
    await broadcast_dashboard({"type": "packages_changed"})
    await broadcast_dashboard({"type": "completion_changed", "packageId": package_id, "status": completion_status})
    return JSONResponse(
        status_code=201 if report["status"] == "valid" else 422,
        content={
            "ok": report["status"] == "valid",
            "packageId": package_id,
            "sessionId": session_id,
            "validationStatus": report["status"],
            "completionStatus": completion_status,
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


@app.get("/api/packages/{package_id}/completion")
def package_completion(package_id: str, request: Request) -> Any:
    check_operator(request)
    package = db.get_package(package_id)
    if not package:
        raise HTTPException(status_code=404, detail="package not found")
    report_value = package.get("completion_report_path")
    if not report_value:
        raise HTTPException(status_code=404, detail="completion report not found")
    report_path = Path(str(report_value))
    if not report_path.is_file():
        raise HTTPException(status_code=404, detail="completion report file not found")
    return json.loads(report_path.read_text(encoding="utf-8"))


@app.get("/api/packages/{package_id}/completion/download")
def package_completion_download(package_id: str, request: Request) -> FileResponse:
    check_operator(request)
    package = db.get_package(package_id)
    if not package:
        raise HTTPException(status_code=404, detail="package not found")
    artifact_value = package.get("completion_artifact_path")
    if not artifact_value:
        raise HTTPException(status_code=404, detail="completion artifact not found")
    path = Path(str(artifact_value))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="completion artifact file not found")
    session_name = safe_name(str(package.get("session_id") or package_id))
    return FileResponse(
        path,
        filename=f"{session_name}_any2full.zip",
        media_type="application/zip",
    )


@app.post("/api/packages/{package_id}/completion/retry")
async def retry_package_completion(package_id: str, request: Request) -> dict[str, Any]:
    check_operator(request)
    package = db.get_package(package_id)
    if not package:
        raise HTTPException(status_code=404, detail="package not found")
    if package.get("validation_status") != "valid":
        raise HTTPException(status_code=409, detail="only valid packages can be completed")
    if package.get("completion_status") in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="completion is already queued or running")
    config = current_completion_config()
    errors = config.readiness_errors(REPOSITORY_ROOT)
    if not config.enabled or errors:
        raise HTTPException(
            status_code=409,
            detail="Any2Full is not ready" + (f": {'; '.join(errors)}" if errors else ""),
        )
    db.queue_package_completion(package_id)
    await broadcast_dashboard(
        {"type": "completion_changed", "packageId": package_id, "status": "queued"}
    )
    return {"ok": True, "packageId": package_id, "completionStatus": "queued"}


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
