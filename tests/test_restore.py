import pytest
from conftest import conversation, drain, send
from emotional_robot.backup import backup_sqlite, restore_sqlite
from emotional_robot.db import make_database
from emotional_robot.ledger import replay_deletions
from emotional_robot.memory import request_deletion
from emotional_robot.models import Memory, MemoryEmbedding, MemoryVersion, Message
from sqlalchemy import select


def test_restore_old_backup_replays_later_deletions(system, tmp_path):
    app, client, a, b = system
    cid = conversation(client, a)
    send(client, a, cid, "请叫我小周")
    drain(app)
    item = client.get("/v1/memories", headers=a).json()["items"][0]
    other = client.post("/v1/memories", headers=b, json={"content": "另一位用户的记忆"}).json()
    backup = tmp_path / "before-delete.db"
    backup_sqlite(app.state.settings, backup)
    client.delete(f"/v1/memories/{item['id']}", headers=a)
    drain(app)
    output = tmp_path / "restored.db"
    result = restore_sqlite(app.state.settings, backup, output)
    assert result["replayed_deletions"] == 1
    engine, factory = make_database("sqlite:///" + str(output))
    with factory() as session:
        restored = session.get(Memory, item["id"])
        assert restored.status == "deleted" and restored.content == ""
        assert session.get(Memory, other["id"]).content == "另一位用户的记忆"
        assert not list(
            session.scalars(select(MemoryVersion).where(MemoryVersion.memory_id == item["id"]))
        )
        assert not list(session.scalars(select(MemoryEmbedding)))
        assert all("小周" not in m.content for m in session.scalars(select(Message)))
    engine.dispose()


def test_restore_requires_original_ledger_and_new_destination(system, tmp_path):
    app, client, a, _ = system
    client.post("/v1/memories", headers=a, json={"content": "一条记忆"})
    backup = tmp_path / "backup.db"
    backup_sqlite(app.state.settings, backup)
    missing = app.state.settings.model_copy(
        update={"deletion_ledger_path": tmp_path / "missing.sqlite"}
    )
    output = tmp_path / "recovered.db"
    with pytest.raises(RuntimeError, match="original deletion ledger"):
        restore_sqlite(missing, backup, output)
    assert not output.exists()
    with pytest.raises(ValueError, match="Destination already exists"):
        backup_sqlite(app.state.settings, backup)


def test_replay_does_not_clear_new_replies_twice(system):
    app, client, a, _ = system
    item = client.post("/v1/memories", headers=a, json={"content": "待删除"}).json()
    client.delete(f"/v1/memories/{item['id']}", headers=a)
    drain(app)
    cid = conversation(client, a)
    send(client, a, cid, "你好")
    before = client.get(f"/v1/conversations/{cid}/messages", headers=a).json()
    assert replay_deletions(app.state.factory, app.state.ledger) == 0
    assert client.get(f"/v1/conversations/{cid}/messages", headers=a).json() == before


def test_journal_survives_primary_transaction_rollback(system):
    app, client, a, _ = system
    item = client.post("/v1/memories", headers=a, json={"content": "需要忘记"}).json()
    with pytest.raises(RuntimeError, match="simulated"):
        with app.state.factory.begin() as session:
            request_deletion(session, session.get(Memory, item["id"]), ledger=app.state.ledger)
            raise RuntimeError("simulated primary failure")
    assert replay_deletions(app.state.factory, app.state.ledger) == 1
    assert client.get(f"/v1/memories/{item['id']}", headers=a).status_code == 404
