"""Exercise an actual loopback server and durable worker; no external model calls."""

import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


def wait_until(check, seconds=10):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        try:
            result = check()
            if result:
                return result
        except httpx.TransportError:
            pass
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for local service or worker")


def answer(text):
    return "".join(
        json.loads(line[6:]).get("text", "")
        for line in text.splitlines()
        if line.startswith("data: ")
    )


def main():
    root = Path(__file__).resolve().parents[1]
    private = root / "data/private"
    private.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="smoke-", dir=private) as directory:
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        token = secrets.token_urlsafe(32)
        env = dict(
            os.environ,
            ROBOT_DATABASE_URL=f"sqlite:///{Path(directory) / 'smoke.db'}",
            ROBOT_DEMO_TOKEN=token,
            ROBOT_DEMO_MODE="true",
            ROBOT_PROVIDER="demo",
            ROBOT_AUTO_WORKER="true",
        )
        server = subprocess.Popen(
            [sys.executable, "-m", "emotional_robot.cli", "serve", "--port", str(port)],
            cwd=root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            with httpx.Client(
                base_url=base, headers={"Authorization": f"Bearer {token}"}, timeout=10
            ) as client:
                wait_until(lambda: client.get("/healthz").is_success)
                assert httpx.get(base + "/v1/memories").status_code == 401
                conversation = client.post("/v1/conversations", json={}).json()["id"]
                first = client.post(
                    f"/v1/conversations/{conversation}/messages",
                    json={"content": "请叫我小周", "client_id": "smoke-1"},
                )
                assert "event: completed" in first.text
                memories = wait_until(lambda: client.get("/v1/memories").json()["items"])
                second_conversation = client.post("/v1/conversations", json={}).json()["id"]
                second = client.post(
                    f"/v1/conversations/{second_conversation}/messages",
                    json={"content": "我叫什么？", "client_id": "smoke-2"},
                )
                assert "小周" in answer(second.text)
                mid = memories[0]["id"]
                edited = client.patch(
                    f"/v1/memories/{mid}", json={"revision": 1, "content": "用户希望被称为小林"}
                )
                assert edited.status_code == 200 and edited.json()["revision"] == 2
                job = client.delete(f"/v1/memories/{mid}").json()
                wait_until(
                    lambda: (
                        client.get(f"/v1/deletion-jobs/{job['id']}").json()["status"] == "completed"
                    )
                )
                assert not client.get("/v1/memories").json()["items"]
                assert client.get(f"/v1/memories/{mid}").status_code == 404
                print(
                    "HTTP smoke passed: auth, SSE, durable extraction, cross-session recall, correction, deletion"
                )
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
            server.communicate()


if __name__ == "__main__":
    main()
