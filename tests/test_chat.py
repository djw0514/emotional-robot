import json

from conftest import conversation, send
from emotional_robot.app import create_app
from emotional_robot.models import Memory
from emotional_robot.providers import DemoProvider, ProviderError
from fastapi.testclient import TestClient


def parse_events(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def test_sse_protocol_and_idempotency(system):
    _, client, a, _ = system
    cid = conversation(client, a)
    first = send(client, a, cid, "你好")
    assert first.headers["content-type"].startswith("text/event-stream")
    events = parse_events(first.text)
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    assert len({e["request_id"] for e in events}) == 1
    second = send(client, a, cid, "你好")
    assert '"replayed": true' in second.text
    assert len(client.get(f"/v1/conversations/{cid}/messages", headers=a).json()) == 2
    assert send(client, a, cid, "different").status_code == 409


def test_model_failure_is_not_fake_success(system):
    app, _, a, _ = system

    class Broken(DemoProvider):
        async def stream(self, history, memories):
            yield "半句话"
            raise ProviderError("network_failure")

    other = create_app(app.state.settings, provider=Broken())
    with TestClient(other) as client:
        cid = conversation(client, a)
        response = send(client, a, cid, "你好")
        assert "event: error" in response.text
        assert "event: completed" not in response.text
        assert len(client.get(f"/v1/conversations/{cid}/messages", headers=a).json()) == 1


def test_deletion_during_generation_cancels_output(system):
    app, _, a, _ = system

    class DeleteDuringStream(DemoProvider):
        async def stream(self, history, memories):
            from emotional_robot.memory import request_deletion

            with app.state.factory.begin() as session:
                request_deletion(session, session.get(Memory, memories[0]["id"]))
            yield "这句不能出现"

    other = create_app(app.state.settings, provider=DeleteDuringStream())
    with TestClient(other) as client:
        client.post("/v1/memories", headers=a, json={"content": "用户喜欢咖啡"})
        response = send(client, a, conversation(client, a), "我喜欢什么？")
        assert "这句不能出现" not in response.text
        assert "event: error" in response.text


def test_database_survives_app_restart(system):
    app, client, a, _ = system
    item = client.post("/v1/memories", headers=a, json={"content": "喜欢绘画"}).json()
    restarted = create_app(app.state.settings)
    with TestClient(restarted) as second:
        assert second.get(f"/v1/memories/{item['id']}", headers=a).json()["content"] == "喜欢绘画"
