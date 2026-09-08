import contextlib
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from server import preview_relay as relay

# The relay transports JPEG bytes without retaining/re-encoding camera frames.
FRAME1 = b'\xff\xd8first\xff\xd9'
FRAME2 = b'\xff\xd8second\xff\xd9'
FRAME3 = b'\xff\xd8latest\xff\xd9'

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('SANDSTORIES_DEVICE_TOKEN', 'device-test')
    monkeypatch.setenv('SANDSTORIES_OPERATOR_TOKEN', 'operator-test')
    relay.publishers.clear()
    relay.viewers.clear()
    app = FastAPI()
    app.include_router(relay.router)
    with TestClient(app) as client:
        yield client
    assert not relay.publishers
    assert not relay.viewers

DEVICE = '/ws/preview/device/phone?token=device-test'
VIEWER = '/ws/preview/viewer/phone?token=operator-test'

@pytest.mark.parametrize('path', ['/ws/preview/device/phone?token=operator-test', '/ws/preview/viewer/phone?token=device-test', '/ws/preview/viewer/phone'])
def test_preview_authentication(client, path):
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(path):
            pass
    assert error.value.code == 1008

def test_demand_frames_and_stop(client):
    with client.websocket_connect(DEVICE) as device:
        assert device.receive_json() == {'type':'preview_demand','viewers':0}
        with client.websocket_connect(VIEWER) as viewer:
            assert device.receive_json() == {'type':'preview_demand','viewers':1}
            viewer.send_text('ready')
            device.send_bytes(FRAME1)
            assert device.receive_json() == {'type':'frame_ack'}
            assert viewer.receive_bytes() == FRAME1
        assert device.receive_json() == {'type':'preview_demand','viewers':0}
        device.send_text('ping')
        assert device.receive_json() == {'type':'preview_pong'}

def test_slow_viewer_receives_latest_not_a_backlog(client):
    with client.websocket_connect(DEVICE) as device:
        device.receive_json()
        with client.websocket_connect(VIEWER) as viewer:
            device.receive_json()
            # No ready credit: no frame may be sent to the browser yet.
            for frame in [FRAME1, FRAME2, FRAME3]:
                device.send_bytes(frame)
                assert device.receive_json()['type'] == 'frame_ack'
            viewer.send_text('ready')
            assert viewer.receive_bytes() == FRAME3

def test_device_isolation(client):
    with client.websocket_connect(DEVICE) as device:
        device.receive_json()
        with client.websocket_connect('/ws/preview/viewer/other?token=operator-test'):
            device.send_text('ping')
            assert device.receive_json() == {'type':'preview_pong'}
            assert len(relay.viewers.get('phone', ())) == 0

@pytest.mark.parametrize('frame', [b'not an image', b'\xff\xd8'+b'x'*relay.MAX_FRAME_BYTES+b'\xff\xd9'], ids=['malformed', 'oversized'])
def test_invalid_and_oversized_frames_close_publisher(client, frame):
    with client.websocket_connect(DEVICE) as device:
        device.receive_json()
        device.send_bytes(frame)
        with pytest.raises(WebSocketDisconnect) as error:
            device.receive_json()
        assert error.value.code == 1009

def test_viewer_limit(client, monkeypatch):
    monkeypatch.setattr(relay, 'MAX_VIEWERS_PER_DEVICE', 1)
    with client.websocket_connect(VIEWER):
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(VIEWER):
                pass
        assert error.value.code == 1013
