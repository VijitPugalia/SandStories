from __future__ import annotations

import os
import time
import uuid

import jwt


def livekit_configured() -> bool:
    return bool(os.environ.get("LIVEKIT_URL") and os.environ.get("LIVEKIT_API_KEY") and os.environ.get("LIVEKIT_API_SECRET"))


def livekit_url() -> str:
    return os.environ.get("LIVEKIT_URL", "ws://localhost:7880")


def create_livekit_token(room: str, identity: str, can_publish: bool, can_subscribe: bool) -> str:
    api_key = os.environ.get("LIVEKIT_API_KEY", "devkey")
    api_secret = os.environ.get("LIVEKIT_API_SECRET", "secret")
    now = int(time.time())
    payload = {
        "iss": api_key,
        "sub": identity,
        "nbf": now - 10,
        "exp": now + 60 * 60,
        "jti": str(uuid.uuid4()),
        "video": {
            "room": room,
            "roomJoin": True,
            "canPublish": can_publish,
            "canSubscribe": can_subscribe,
            "canPublishData": True,
        },
    }
    return jwt.encode(payload, api_secret, algorithm="HS256")
