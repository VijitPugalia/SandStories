from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
from urllib import request
from urllib import error

import job_gateway


class GatewayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        (root / "submit.token").write_text("s" * 32, encoding="utf-8")
        (root / "admin.token").write_text("a" * 32, encoding="utf-8")
        result_code = (
            "import json,os,pathlib; "
            "p=pathlib.Path(os.environ['SANDSTORIES_RESULT_FILE']); "
            "p.write_text(json.dumps(dict(output_path=str(p.parent/'output'),"
            "review_required=False)))"
        )
        self.config = {
            "listen_host": "127.0.0.1",
            "listen_port": 0,
            "database_path": str(root / "jobs.sqlite3"),
            "storage_root": str(root / "storage"),
            "scratch_root": str(root / "scratch"),
            "submit_token_file": str(root / "submit.token"),
            "admin_token_file": str(root / "admin.token"),
            "max_upload_bytes": 1024 * 1024,
            "max_chunk_bytes": 8,
            "poll_seconds": 0.01,
            "manual_review_required": False,
            "webhook_allowed_hosts": [],
            "webhook_max_attempts": 1,
            "pipeline_command": [job_gateway.sys.executable, "-c", result_code],
        }
        self.server = job_gateway.GatewayServer(self.config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def call(self, method: str, path: str, token: str, body: bytes = b"", **headers):
        outgoing = request.Request(
            self.base + path,
            data=body if method in {"POST", "PATCH"} else None,
            method=method,
            headers={"Authorization": f"Bearer {token}", **headers},
        )
        with request.urlopen(outgoing, timeout=5) as response:
            raw = response.read()
            return response, json.loads(raw) if raw else {}

    def test_resumable_upload_commit_and_worker(self) -> None:
        payload = b"gateway-test-payload"
        create = json.dumps(
            {
                "filename": "capture.MKV",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ).encode()
        _, created = self.call(
            "POST", "/v1/jobs", "s" * 32, create, **{"Content-Type": "application/json"}
        )
        job_id = created["job"]["id"]
        token = created["job_token"]
        offset = 0
        for chunk in (payload[:8], payload[8:16], payload[16:]):
            response, _ = self.call(
                "PATCH",
                f"/v1/jobs/{job_id}/input",
                token,
                chunk,
                **{"Upload-Offset": str(offset), "Content-Type": "application/offset+octet-stream"},
            )
            offset = int(response.headers["Upload-Offset"])
        self.assertEqual(offset, len(payload))
        self.call("POST", f"/v1/jobs/{job_id}/commit", token)
        job_gateway.worker_loop(self.config, once=True)
        _, status = self.call("GET", f"/v1/jobs/{job_id}", token)
        self.assertEqual(status["job"]["state"], "completed", status["job"])
        self.assertEqual(status["job"]["sha256"], hashlib.sha256(payload).hexdigest())
        log_request = request.Request(
            self.base + f"/v1/jobs/{job_id}/log",
            headers={"Authorization": f"Bearer {token}"},
        )
        with request.urlopen(log_request, timeout=5) as response:
            self.assertIn(b"command:", response.read())
            self.assertIn("attachment", response.headers["Content-Disposition"])

    def test_automatic_pipeline_completion_has_no_review_gate(self) -> None:
        payload = b"automatic-gate-test"
        create = json.dumps(
            {
                "filename": "capture.tar",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ).encode()
        _, created = self.call(
            "POST", "/v1/jobs", "s" * 32, create, **{"Content-Type": "application/json"}
        )
        job_id = created["job"]["id"]
        token = created["job_token"]
        offset = 0
        for chunk in (payload[:8], payload[8:16], payload[16:]):
            response, _ = self.call(
                "PATCH", f"/v1/jobs/{job_id}/input", token, chunk,
                **{"Upload-Offset": str(offset), "Content-Type": "application/offset+octet-stream"},
            )
            offset = int(response.headers["Upload-Offset"])
        self.call("POST", f"/v1/jobs/{job_id}/commit", token)

        job_gateway.worker_loop(self.config, once=True)
        _, status = self.call("GET", f"/v1/jobs/{job_id}", token)
        self.assertEqual(status["job"]["state"], "completed")
        _, history = self.call("GET", f"/v1/jobs/{job_id}/events", token)
        event_states = [event["state"] for event in history["events"]]
        self.assertNotIn("review_required", event_states)

    def test_job_format_options_are_validated_persisted_and_exported(self) -> None:
        result_code = (
            "import json,os,pathlib; "
            "p=pathlib.Path(os.environ['SANDSTORIES_RESULT_FILE']); "
            "p.write_text(json.dumps(dict(output_path=str(p.parent/'output'),review_required=False,"
            "options=dict((k,os.environ[k]) for k in ('SANDSTORIES_INPUT_FORMAT','SANDSTORIES_OUTPUT_FORMAT','SANDSTORIES_RGB_RESOLUTION','SANDSTORIES_FALLBACK_FPS')))))"
        )
        self.config["pipeline_command"] = [job_gateway.sys.executable, "-c", result_code]
        payload = b"stream-bundle"
        create = json.dumps(
            {
                "filename": "capture.zip",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "input_format": "stream-bundle",
                "output_format": "lossless-streams",
                "rgb_resolution": "50-percent",
                "fallback_fps": 29.97,
            }
        ).encode()
        _, created = self.call("POST", "/v1/jobs", "s" * 32, create, **{"Content-Type": "application/json"})
        job = created["job"]
        self.assertEqual(job["input_format"], "stream-bundle")
        self.assertEqual(job["output_format"], "lossless-streams")
        self.assertEqual(job["rgb_resolution"], "50-percent")
        token = created["job_token"]
        offset = 0
        for chunk in (payload[:8], payload[8:]):
            response, _ = self.call(
                "PATCH", f"/v1/jobs/{job['id']}/input", token, chunk,
                **{"Upload-Offset": str(offset), "Content-Type": "application/offset+octet-stream"},
            )
            offset = int(response.headers["Upload-Offset"])
        self.call("POST", f"/v1/jobs/{job['id']}/commit", token)
        job_gateway.worker_loop(self.config, once=True)
        row = self.server.store.get(job["id"])
        self.assertEqual(row["state"], "completed", row["error"])
        result = json.loads((self.server.job_root(job["id"]) / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["options"]["SANDSTORIES_INPUT_FORMAT"], "stream-bundle")
        self.assertEqual(result["options"]["SANDSTORIES_OUTPUT_FORMAT"], "lossless-streams")
        self.assertEqual(result["options"]["SANDSTORIES_RGB_RESOLUTION"], "50-percent")
        self.assertEqual(float(result["options"]["SANDSTORIES_FALLBACK_FPS"]), 29.97)

    def test_completed_artifact_download_supports_ranges(self) -> None:
        now = job_gateway.utc_now()
        job_id = "sj_" + "f" * 32
        job_token = "j" * 32
        job_root = self.server.job_root(job_id)
        output = job_root / "output" / "final_v12"
        output.mkdir(parents=True)
        artifact = job_root / "artifacts" / f"{job_id}-final-v12.tar.zst"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"0123456789")
        zip_artifact = job_root / "artifacts" / f"{job_id}-final-v12.zip"
        zip_artifact.write_bytes(b"abcdefghij")
        with self.server.store.connect() as db:
            db.execute(
                "INSERT INTO jobs(id,created_at,updated_at,filename,size_bytes,sha256,upload_offset,"
                "state,stage,progress,message,profile,job_token_hash,output_path) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    now,
                    now,
                    "done.mkv",
                    1,
                    "0" * 64,
                    1,
                    "completed",
                    "completed",
                    1.0,
                    "done",
                    "azure-hand-free-v12",
                    job_gateway.token_hash(job_token),
                    str(output),
                ),
            )

        outgoing = request.Request(
            self.base + f"/v1/jobs/{job_id}/artifact",
            headers={"Authorization": f"Bearer {job_token}", "Range": "bytes=2-5"},
        )
        with request.urlopen(outgoing, timeout=5) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b"2345")
            self.assertEqual(response.headers["Content-Range"], "bytes 2-5/10")
            self.assertEqual(response.headers["Accept-Ranges"], "bytes")
        zip_request = request.Request(
            self.base + f"/v1/jobs/{job_id}/artifact.zip",
            headers={"Authorization": f"Bearer {job_token}", "Range": "bytes=3-6"},
        )
        with request.urlopen(zip_request, timeout=5) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b"defg")
            self.assertEqual(response.headers["Content-Type"], "application/zip")

    def test_failure_preserves_stage_and_complete_log(self) -> None:
        failure_code = (
            "import json,os,pathlib,sys; "
            "pathlib.Path(os.environ['SANDSTORIES_PROGRESS_FILE']).write_text("
            "json.dumps(dict(stage='decode_mkv',progress=.03,message='decoder rejected frame 9'))); "
            "print('complete-log-marker', flush=True); sys.exit(7)"
        )
        self.config["pipeline_command"] = [job_gateway.sys.executable, "-c", failure_code]
        payload = b"mkv"
        create = json.dumps(
            {
                "filename": "failure.mkv",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ).encode()
        _, created = self.call(
            "POST", "/v1/jobs", "s" * 32, create, **{"Content-Type": "application/json"}
        )
        job_id = created["job"]["id"]
        token = created["job_token"]
        self.call(
            "PATCH", f"/v1/jobs/{job_id}/input", token, payload,
            **{"Upload-Offset": "0", "Content-Type": "application/offset+octet-stream"},
        )
        self.call("POST", f"/v1/jobs/{job_id}/commit", token)
        job_gateway.worker_loop(self.config, once=True)
        _, status = self.call("GET", f"/v1/jobs/{job_id}", token)
        self.assertEqual(status["job"]["state"], "failed")
        self.assertEqual(status["job"]["stage"], "decode_mkv")
        self.assertIn("decoder rejected frame 9", status["job"]["message"])
        _, failure = self.call("GET", f"/v1/jobs/{job_id}/failure", token)
        self.assertEqual(failure["stage"], "decode_mkv")
        log_request = request.Request(
            self.base + f"/v1/jobs/{job_id}/log",
            headers={"Authorization": f"Bearer {token}"},
        )
        with request.urlopen(log_request, timeout=5) as response:
            log = response.read()
        self.assertIn(b"complete-log-marker", log)
        self.assertIn(b"worker failure in stage decode_mkv", log)

    def test_web_session_csrf_ownership_and_pkce_start(self) -> None:
        self.config.update(
            {
                "web_auth_enabled": True,
                "public_base_url": "https://sandstories.example.test",
                "cookie_path": "/",
                "github_oauth_client_id": "test-client",
                "bootstrap_admin_emails": ["admin@example.test"],
            }
        )
        now = job_gateway.utc_now()
        session_token = "w" * 40
        csrf = "c" * 40
        with self.server.store.connect() as db:
            user_id = db.execute(
                "INSERT INTO users(github_id,github_login,email,role,created_at,updated_at,last_login_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (123, "uploader", "user@example.test", "uploader", now, now, now),
            ).lastrowid
            db.execute(
                "INSERT INTO web_sessions(token_hash,user_id,csrf_token,created_at,expires_epoch,last_seen_at) "
                "VALUES(?,?,?,?,?,?)",
                (job_gateway.token_hash(session_token), user_id, csrf, now, job_gateway.time.time() + 3600, now),
            )

        with request.urlopen(
            request.Request(self.base + "/ui", headers={"Cookie": f"sandstories_session={session_token}"}),
            timeout=5,
        ) as response:
            page = response.read()
            self.assertIn(b"Submit capture", page)
            self.assertIn(b"compact-streams", page)
            self.assertIn(b"lossless-streams", page)
            self.assertIn(b"rgbResolution", page)
            self.assertIn(b"fallbackFps", page)

        body = json.dumps(
            {"filename": "web.tar", "size_bytes": 12, "sha256": "auto"}
        ).encode()
        no_csrf = request.Request(
            self.base + "/v1/jobs", data=body, method="POST",
            headers={"Cookie": f"sandstories_session={session_token}", "Content-Type": "application/json"},
        )
        with self.assertRaises(error.HTTPError) as denied:
            request.urlopen(no_csrf, timeout=5)
        self.assertEqual(denied.exception.code, 403)

        allowed = request.Request(
            self.base + "/v1/jobs", data=body, method="POST",
            headers={
                "Cookie": f"sandstories_session={session_token}",
                "Content-Type": "application/json",
                "X-CSRF-Token": csrf,
            },
        )
        with request.urlopen(allowed, timeout=5) as response:
            created = json.loads(response.read())
        row = self.server.store.get(created["job"]["id"])
        self.assertEqual(row["owner_user_id"], user_id)

        outgoing = request.Request(self.base + "/auth/github")
        # Do not follow the redirect to GitHub during the unit test.
        class NoRedirect(request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        with self.assertRaises(error.HTTPError) as redirect:
            request.build_opener(NoRedirect).open(outgoing, timeout=5)
        location = redirect.exception.headers["Location"]
        self.assertIn("code_challenge_method=S256", location)
        self.assertNotIn("scope=", location)

    def test_dead_worker_is_failed_instead_of_blocking_queue(self) -> None:
        now = job_gateway.utc_now()
        job_id = "sj_" + "d" * 32
        root = self.server.job_root(job_id)
        (root / "input").mkdir(parents=True)
        with self.server.store.connect() as db:
            db.execute(
                "INSERT INTO jobs(id,created_at,updated_at,filename,size_bytes,sha256,upload_offset,"
                "state,stage,progress,message,profile,job_token_hash,worker_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, now, now, "dead.tar", 1, "0" * 64, 1, "running", "pipeline", 0.4,
                 "running", "azure-hand-free-v12", job_gateway.token_hash("j" * 32),
                 "definitely-not-this-host:99999999"),
            )
        worker_id = f"{job_gateway.os.uname().nodename if hasattr(job_gateway.os, 'uname') else job_gateway.os.getenv('COMPUTERNAME', 'worker')}:{job_gateway.os.getpid()}"
        job_gateway.recover_orphaned_jobs(self.server.store, worker_id)
        row = self.server.store.get(job_id)
        self.assertEqual(row["state"], "failed")
        self.assertIn("worker process ended", row["message"])

    def test_webhook_is_hmac_signed_and_marked_delivered(self) -> None:
        now = job_gateway.utc_now()
        job_id = "sj_" + "e" * 32
        webhook_secret = "hook-secret-" + "x" * 32
        with self.server.store.connect() as db:
            db.execute(
                "INSERT INTO jobs(id,created_at,updated_at,filename,size_bytes,sha256,upload_offset,"
                "state,stage,progress,message,profile,job_token_hash,webhook_url,webhook_secret) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, now, now, "hook.tar", 1, "0" * 64, 1, "completed", "completed", 1.0,
                 "done", "azure-hand-free-v12", job_gateway.token_hash("j" * 32),
                 "https://hooks.example.test/sandstories", webhook_secret),
            )
        self.server.store.enqueue_webhook(job_id, "job.completed")
        captured = {}

        class FakeResponse:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class FakeOpener:
            def open(self, outgoing, timeout):
                captured["body"] = outgoing.data
                captured["signature"] = outgoing.get_header("X-sandstories-signature-256")
                return FakeResponse()

        with mock.patch.object(job_gateway.request, "build_opener", return_value=FakeOpener()):
            job_gateway.deliver_due_webhooks(self.config, self.server.store)
        expected = "sha256=" + job_gateway.hmac.new(
            webhook_secret.encode(), captured["body"], job_gateway.hashlib.sha256
        ).hexdigest()
        self.assertEqual(captured["signature"], expected)
        with self.server.store.connect() as db:
            delivery = db.execute(
                "SELECT delivered_at,attempt FROM webhook_deliveries WHERE job_id=?", (job_id,)
            ).fetchone()
        self.assertIsNotNone(delivery["delivered_at"])
        self.assertEqual(delivery["attempt"], 1)

    def test_oauth_callback_accepts_token_response_without_scope_field(self) -> None:
        self.config.update(
            {
                "web_auth_enabled": True,
                "public_base_url": "https://sandstories.example.test",
                "cookie_path": "/",
                "github_oauth_client_id": "test-client",
                "bootstrap_admin_emails": ["admin@example.test"],
                "session_hours": 12,
            }
        )
        self.server.github_client_secret = "test-secret"
        state = "oauth-state-" + "s" * 32
        with self.server.store.connect() as db:
            db.execute(
                "INSERT INTO oauth_flows(state_hash,code_verifier,expires_epoch) VALUES(?,?,?)",
                (job_gateway.token_hash(state), "verifier", job_gateway.time.time() + 600),
            )
        payloads = iter(
            (
                {"access_token": "temporary-token"},
                {"id": 4752841, "login": "bootstrap-admin", "avatar_url": ""},
                [{"email": "admin@example.test", "verified": True, "primary": True}],
            )
        )

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(self.payload).encode()

        class FakeOpener:
            def open(self, outgoing, timeout):
                return FakeResponse(next(payloads))

        class NoRedirect(request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        self.server.oauth_opener = FakeOpener()
        outgoing = request.Request(
            self.base + f"/auth/github/callback?code=test-code&state={state}",
            headers={"Cookie": f"sandstories_oauth_state={state}"},
        )
        with self.assertRaises(error.HTTPError) as redirect:
            request.build_opener(NoRedirect).open(outgoing, timeout=5)
        self.assertEqual(redirect.exception.code, 303)
        with self.server.store.connect() as db:
            user = db.execute("SELECT email,role FROM users WHERE github_id=4752841").fetchone()
        self.assertEqual(user["email"], "admin@example.test")
        self.assertEqual(user["role"], "admin")


if __name__ == "__main__":
    unittest.main()
