"""Bounded JPEG preview relay on the field console's existing HTTP/WebSocket port."""
from __future__ import annotations

import asyncio
import contextlib
import os
import anyio
from dataclasses import dataclass, field

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
MAX_FRAME_BYTES = 512 * 1024
MAX_VIEWERS_PER_DEVICE = 8

@dataclass(eq=False)
class Publisher:
    socket: WebSocket
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, message: dict) -> None:
        async with self.lock:
            await asyncio.wait_for(self.socket.send_json(message), timeout=5)

publishers: dict[str, Publisher] = {}
viewers: dict[str, set[asyncio.Queue]] = {}

async def notify_demand(device_id: str) -> None:
    publisher = publishers.get(device_id)
    if publisher:
        with contextlib.suppress(Exception):
            await publisher.send({'type': 'preview_demand', 'viewers': len(viewers.get(device_id, ()))})

def offer_latest(queue: asyncio.Queue, frame: bytes | None) -> None:
    if queue.full():
        queue.get_nowait()
    queue.put_nowait(frame)

@router.websocket('/ws/preview/device/{device_id}')
async def preview_device(socket: WebSocket, device_id: str) -> None:
    if socket.query_params.get('token') != os.environ.get('SANDSTORIES_DEVICE_TOKEN', 'field-device'):
        await socket.close(code=1008)
        return
    await socket.accept()
    publisher = Publisher(socket)
    previous = publishers.get(device_id)
    publishers[device_id] = publisher
    if previous:
        with contextlib.suppress(Exception):
            await previous.socket.close(code=1000)
    try:
        await notify_demand(device_id)
        while True:
            message = await socket.receive()
            if message['type'] == 'websocket.disconnect':
                break
            if publishers.get(device_id) is not publisher:
                break
            frame = message.get('bytes')
            if frame is None:
                # Application heartbeat keeps the tunnel alive even with no viewers.
                await publisher.send({'type': 'preview_pong'})
                continue
            if len(frame) > MAX_FRAME_BYTES or not frame.startswith(b'\xff\xd8') or not frame.endswith(b'\xff\xd9'):
                await socket.close(code=1009)
                break
            for queue in tuple(viewers.get(device_id, ())):
                offer_latest(queue, frame)
            await publisher.send({'type': 'frame_ack'})
    except WebSocketDisconnect:
        pass
    finally:
        if publishers.get(device_id) is publisher:
            publishers.pop(device_id, None)
            for queue in tuple(viewers.get(device_id, ())):
                offer_latest(queue, None)

@router.websocket('/ws/preview/viewer/{device_id}')
async def preview_viewer(socket: WebSocket, device_id: str) -> None:
    if socket.query_params.get('token') != os.environ.get('SANDSTORIES_OPERATOR_TOKEN', 'field-console'):
        await socket.close(code=1008)
        return
    queues = viewers.setdefault(device_id, set())
    if len(queues) >= MAX_VIEWERS_PER_DEVICE:
        await socket.close(code=1013)
        return
    await socket.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    queues.add(queue)
    ready = asyncio.Event()

    async def receive_ready() -> None:
        while True:
            message = await socket.receive_text()
            if message == 'ready':
                ready.set()

    async def send_latest() -> None:
        while True:
            await ready.wait()
            try:
                frame = await asyncio.wait_for(queue.get(), timeout=10)
            except TimeoutError:
                await socket.send_json({'type': 'preview_waiting'})
                continue
            ready.clear()
            if frame is None:
                await socket.send_json({'type': 'preview_waiting'})
            else:
                await asyncio.wait_for(socket.send_bytes(frame), timeout=10)

    tasks = [asyncio.create_task(receive_ready()), asyncio.create_task(send_latest())]
    try:
        await notify_demand(device_id)
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            with contextlib.suppress(WebSocketDisconnect, RuntimeError, TimeoutError):
                task.result()
    except asyncio.CancelledError:
        pass
    finally:
        queues.discard(queue)
        if not queues and viewers.get(device_id) is queues:
            viewers.pop(device_id, None)
        for task in tasks:
            task.cancel()
        with anyio.CancelScope(shield=True):
            await asyncio.gather(*tasks, return_exceptions=True)
            await notify_demand(device_id)
