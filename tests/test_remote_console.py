import json
from pathlib import Path
import jwt
import pytest
from fastapi.testclient import TestClient
from server import app as server

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('SANDSTORIES_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('SANDSTORIES_OPERATOR_TOKEN', 'test-operator')
    monkeypatch.setenv('SANDSTORIES_DEVICE_TOKEN', 'test-device')
    monkeypatch.setenv('SANDSTORIES_ANY2FULL_ENABLED', 'false')
    monkeypatch.setenv('LIVEKIT_URL', 'wss://preview.example.test')
    monkeypatch.delenv('LIVEKIT_API_SECRET', raising=False)
    monkeypatch.delenv('LIVEKIT_API_KEY', raising=False)
    server.device_sockets.clear()
    server.dashboard_sockets.clear()
    with TestClient(server.app) as client:
        yield client

AUTH = {'X-SandStories-Token': 'test-operator'}
COMMANDS = ['start_recording', 'pause_recording', 'resume_recording', 'mark_segment', 'stop_recording', 'upload_last_session', 'ping']

@pytest.mark.parametrize('command', COMMANDS)
def test_command_roundtrip(client, command):
    with client.websocket_connect('/ws/device/phone?token=test-device&name=Phone') as device:
        with client.websocket_connect('/ws/dashboard?token=test-operator') as dashboard:
            arguments = {'recordAudio': False} if command == 'start_recording' else {}
            response = client.post('/api/devices/phone/commands', headers=AUTH, json={'type': command, 'payload': arguments})
            assert response.status_code == 200
            message = device.receive_json()
            assert message == {'type': 'command', 'commandId': response.json()['commandId'], 'name': command, 'payload': arguments}
            assert dashboard.receive_json()['type'] == 'command_sent'
            for kind, status in [('command_ack', 'accepted'), ('command_result', 'completed')]:
                receipt = {'type': kind, 'commandId': message['commandId'], 'status': status}
                device.send_json(receipt)
                assert dashboard.receive_json()['message'] == receipt

@pytest.mark.parametrize('body', [{'type':'bogus'}, {'type': []}, {'type':'start_recording','payload': []}, {'type':'start_recording','payload': {'recordAudio':'false'}}, {'type':'pause_recording','payload': {'recordAudio':True}}])
def test_invalid_command_rejected(client, body):
    assert client.post('/api/devices/phone/commands', headers=AUTH, json=body).status_code == 422

def test_auth_and_offline(client):
    assert client.post('/api/devices/phone/commands', json={'type':'ping'}).status_code == 401
    assert client.post('/api/devices/phone/commands', headers=AUTH, json={'type':'ping'}).status_code == 409

def test_receipts_do_not_replace_device_status(client):
    with client.websocket_connect('/ws/device/phone?token=test-device&name=Phone') as device:
        with client.websocket_connect('/ws/dashboard?token=test-operator') as dashboard:
            status = {'type':'device_status','deviceName':'Phone','recording':True,'paused':True,'savedFrames':10}
            device.send_json(status)
            dashboard.receive_json()
            device.send_json({'type':'command_ack','commandId':'x','status':'accepted'})
            dashboard.receive_json()
            row = client.get('/api/devices', headers=AUTH).json()[0]
            assert row['name'] == 'Phone'
            assert json.loads(row['last_status_json']) == status

@pytest.mark.parametrize('endpoint', ['ws://localhost:7880','ws://127.0.0.1:7880','ws://[::1]:7880','http://example.test',''])
def test_unreachable_preview_configuration(client, monkeypatch, endpoint):
    monkeypatch.setenv('LIVEKIT_URL',endpoint)
    response = client.get('/api/livekit/token?room=device_phone&identity=viewer', headers=AUTH)
    assert response.status_code == 503

def test_livekit_development_key_matches_server_yaml(client):
    response = client.get('/api/livekit/token?room=device_phone&identity=viewer', headers=AUTH)
    assert response.status_code == 200
    secret = Path('deploy/livekit.yaml').read_text().split('devkey: ')[1].strip()
    claims = jwt.decode(response.json()['token'], secret, algorithms=['HS256'])
    assert claims['video']['canSubscribe'] is True
    assert claims['video']['canPublish'] is False
    response = client.get('/api/livekit/token?room=device_phone&identity=phone&role=device', headers={'X-SandStories-Token':'test-device'})
    claims = jwt.decode(response.json()['token'], secret, algorithms=['HS256'])
    assert claims['video']['canPublish'] is True
    assert claims['video']['canSubscribe'] is False


def test_dashboard_versions_assets_and_disables_html_cache(client):
    import hashlib
    response = client.get('/')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    for filename in ['dashboard.js', 'dashboard.css']:
        content = Path('server/static', filename).read_bytes()
        digest = hashlib.sha256(content).hexdigest()[:16]
        url = f'/static/{filename}?v={digest}'
        assert f'"{url}"' in response.text
        assert client.get(url).content == content
    assert client.get('/api/health').json()['dashboardVersion'] == server.dashboard_asset_version('dashboard.js')


def test_asset_url_changes_when_deployed_script_changes(client, tmp_path, monkeypatch):
    static = tmp_path / 'static'
    static.mkdir()
    for filename in ['dashboard.html', 'dashboard.js', 'dashboard.css']:
        (static / filename).write_bytes(Path('server/static', filename).read_bytes())
    monkeypatch.setattr(server, 'BASE_DIR', tmp_path)
    old_page = client.get('/').text
    old_version = client.get('/api/health').json()['dashboardVersion']
    with (static / 'dashboard.js').open('ab') as script:
        script.write(b'\n// new deployment\n')
    new_page = client.get('/').text
    new_version = client.get('/api/health').json()['dashboardVersion']
    assert old_version != new_version
    assert f'dashboard.js?v={old_version}' in old_page
    assert f'dashboard.js?v={new_version}' in new_page
    assert f'dashboard.js?v={old_version}' not in new_page
