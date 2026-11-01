import json
import time

from conftest import conversation, drain, send
from emotional_robot.models import Memory, MemoryVersion, Message, Task
from sqlalchemy import select, update


def test_auth_and_id_injection(system):
    _, client, a, b = system
    assert client.get("/v1/memories").status_code == 401
    assert client.get("/v1/me", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert (
        client.post(
            "/v1/memories", headers=a, json={"content": "a", "user_id": "victim"}
        ).status_code
        == 422
    )
    cid = conversation(client, a)
    assert client.get(f"/v1/conversations/{cid}/messages", headers=b).status_code == 404
    assert send(client, b, cid, "你好").status_code == 404


def test_memory_scope_and_export(system):
    _, client, a, b = system
    memory = client.post(
        "/v1/memories", headers=a, json={"content": "我的秘密偏好", "character_id": "private"}
    ).json()
    mid = memory["id"]
    assert client.get("/v1/memories", headers=b).json()["items"] == []
    assert (
        client.get("/v1/memories?character_id=private", headers=a).json()["items"][0]["id"] == mid
    )
    assert client.get("/v1/memories", headers=a).json()["items"] == []
    for method in (client.get, client.delete):
        assert method(f"/v1/memories/{mid}", headers=b).status_code == 404
    assert (
        client.patch(
            f"/v1/memories/{mid}", headers=b, json={"revision": 1, "content": "hack"}
        ).status_code
        == 404
    )
    assert client.get("/v1/memory-export", headers=b).json()["memories"] == []


def test_cross_session_memory_and_evidence(system):
    app, client, a, _ = system
    cid = conversation(client, a)
    assert "event: completed" in send(client, a, cid, "请叫我小周").text
    drain(app)
    item = client.get("/v1/memories", headers=a).json()["items"][0]
    detail = client.get(f"/v1/memories/{item['id']}", headers=a).json()
    assert detail["evidence"][0]["content"] == "请叫我小周"
    other = conversation(client, a)
    result = send(client, a, other, "我叫什么？").text
    answer = "".join(
        json.loads(line[6:]).get("text", "")
        for line in result.splitlines()
        if line.startswith("data: ")
    )
    assert "小周" in answer
    assert item["id"] in result
    private = conversation(client, a, character_id="different")
    assert "小周" not in send(client, a, private, "我叫什么？").text


def test_pause_and_per_message_opt_out(system):
    app, client, a, _ = system
    cid = conversation(client, a)
    client.patch("/v1/memory-settings", headers=a, json={"memory_enabled": False})
    send(client, a, cid, "我喜欢香菜")
    client.patch("/v1/memory-settings", headers=a, json={"memory_enabled": True})
    send(client, a, cid, "我住在杭州", client_id="m2", remember=False)
    drain(app)
    assert client.get("/v1/memories", headers=a).json()["items"] == []
    assert len(client.get(f"/v1/conversations/{cid}/messages", headers=a).json()) == 4


def test_revision_conflict_and_history(system):
    _, client, a, _ = system
    item = client.post("/v1/memories", headers=a, json={"content": "喜欢咖啡"}).json()
    path = f"/v1/memories/{item['id']}"
    result = client.patch(
        path, headers=a, json={"revision": 1, "content": "现在不喝咖啡", "reason": "change"}
    )
    assert result.status_code == 200
    assert result.json()["revision"] == 2
    assert (
        client.patch(path, headers=a, json={"revision": 1, "content": "旧编辑"}).status_code == 409
    )
    detail = client.get(path, headers=a).json()
    assert [v["content"] for v in detail["versions"]] == ["喜欢咖啡", "现在不喝咖啡"]


def test_conflicting_fact_requires_confirmation(system):
    app, client, a, _ = system
    cid = conversation(client, a)
    send(client, a, cid, "我住在杭州")
    drain(app)
    send(client, a, cid, "我现在住在上海", client_id="new-location")
    drain(app)
    candidate = client.get("/v1/memories?status=candidate", headers=a).json()["items"][0]
    assert "上海" in candidate["content"]
    assert "杭州" in client.get("/v1/memories", headers=a).json()["items"][0]["content"]
    response = client.patch(
        f"/v1/memories/{candidate['id']}",
        headers=a,
        json={"revision": 1, "status": "active", "reason": "confirmation"},
    )
    assert response.status_code == 200
    active = client.get("/v1/memories", headers=a).json()["items"]
    assert len(active) == 1 and "上海" in active[0]["content"]


def test_delete_purges_source_history_cached_replies_and_replay(system):
    app, client, a, b = system
    cid = conversation(client, a)
    send(client, a, cid, "请叫我小周")
    drain(app)
    item = client.get("/v1/memories", headers=a).json()["items"][0]
    detail = client.get(f"/v1/memories/{item['id']}", headers=a).json()
    source_id = detail["evidence"][0]["id"]
    send(client, a, conversation(client, a), "我叫什么？")
    job = client.delete(f"/v1/memories/{item['id']}", headers=a).json()
    assert client.get("/v1/memories", headers=a).json()["items"] == []
    assert client.get(f"/v1/memories/{item['id']}", headers=a).status_code == 404
    assert client.get(f"/v1/deletion-jobs/{job['id']}", headers=b).status_code == 404
    assert client.delete(f"/v1/memories/{item['id']}", headers=a).json()["id"] == job["id"]
    drain(app)
    assert client.get(f"/v1/deletion-jobs/{job['id']}", headers=a).json()["status"] == "completed"
    with app.state.factory.begin() as session:
        task = session.scalar(
            select(Task).where(Task.kind == "extract", Task.dedupe_key == source_id)
        )
        task.status, task.attempts = "pending", 0
    drain(app)
    with app.state.factory() as session:
        assert session.get(Memory, item["id"]).content == ""
        assert session.get(Message, source_id).content == ""
        assert not list(session.scalars(select(MemoryVersion)))
    assert "小周" not in client.get(f"/v1/conversations/{cid}/messages", headers=a).text
    assert "小周" not in send(client, a, conversation(client, a), "我叫什么？").text


def test_duplicate_sources_are_all_removed(system):
    app, client, a, _ = system
    cid = conversation(client, a)
    send(client, a, cid, "我喜欢香菜")
    drain(app)
    send(client, a, cid, "我喜欢香菜", client_id="again")
    drain(app)
    items = client.get("/v1/memories", headers=a).json()["items"]
    assert len(items) == 1
    detail = client.get(f"/v1/memories/{items[0]['id']}", headers=a).json()
    assert len(detail["evidence"]) == 2
    client.delete(f"/v1/memories/{items[0]['id']}", headers=a)
    drain(app)
    assert "香菜" not in client.get(f"/v1/conversations/{cid}/messages", headers=a).text


def test_expired_memory_not_recalled(system):
    _, client, a, _ = system
    client.post(
        "/v1/memories", headers=a, json={"content": "我喜欢香菜", "expires_at": time.time() - 10}
    )
    result = send(client, a, conversation(client, a), "我喜欢什么？")
    assert "香菜" not in result.text


def test_worker_expired_lease_and_retry(system):
    app, client, a, _ = system
    cid = conversation(client, a)
    send(client, a, cid, "我不喜欢香菜")
    with app.state.factory.begin() as session:
        session.execute(
            update(Task)
            .where(Task.kind == "extract")
            .values(status="running", attempts=1, lease_until=time.time() - 2)
        )
    drain(app)
    item = client.get("/v1/memories", headers=a).json()["items"][0]
    assert "不喜欢" in item["content"]
    assert client.get("/v1/tasks", headers=a).json()[0]["attempts"] == 2


def test_ambiguous_or_secret_text_not_auto_stored(system):
    app, client, a, _ = system
    cid = conversation(client, a)
    for n, text in enumerate(
        ["假设我住在北京", "小李说他喜欢猫", "我喜欢什么？", "我的密码是123", "今天有点烦"]
    ):
        send(client, a, cid, text, client_id=f"ambiguity-{n}")
    drain(app)
    assert client.get("/v1/memories", headers=a).json()["items"] == []


def test_exhausted_crashed_task_is_visible_and_retryable(system):
    app, client, a, b = system
    send(client, a, conversation(client, a), "我喜欢香菜")
    with app.state.factory.begin() as session:
        task = session.scalar(select(Task).where(Task.kind == "extract"))
        task.status, task.attempts, task.lease_until = "running", 3, time.time() - 2
        tid = task.id
    drain(app)
    assert client.get("/v1/tasks", headers=a).json()[0]["status"] == "failed"
    assert client.post(f"/v1/tasks/{tid}/retry", headers=b).status_code == 404
    assert client.post(f"/v1/tasks/{tid}/retry", headers=a).status_code == 200
    drain(app)
    assert len(client.get("/v1/memories", headers=a).json()["items"]) == 1


def test_deepseek_pipeline_requires_confirmation(system):
    from emotional_robot.app import create_app
    from emotional_robot.providers import DemoProvider
    from fastapi.testclient import TestClient

    app, _, a, _ = system
    online = create_app(
        app.state.settings.model_copy(update={"provider": "compatible"}), provider=DemoProvider()
    )
    with TestClient(online) as client:
        send(client, a, conversation(client, a), "请叫我小周")
        drain(online)
        assert client.get("/v1/memories", headers=a).json()["items"] == []
        candidate = client.get("/v1/memories?status=candidate", headers=a).json()["items"][0]
        assert (
            client.patch(
                f"/v1/memories/{candidate['id']}",
                headers=a,
                json={"revision": 1, "status": "active", "reason": "confirmation"},
            ).status_code
            == 200
        )
        assert client.get("/v1/memories", headers=a).json()["items"][0]["id"] == candidate["id"]
