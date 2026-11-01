import time

import httpx
import pytest
from conftest import drain
from emotional_robot.app import create_app
from emotional_robot.config import Settings
from emotional_robot.embeddings import Embedder, EmbeddingError
from emotional_robot.models import Memory, MemoryEmbedding, Task
from emotional_robot.retrieval import queue_index
from fastapi.testclient import TestClient
from sqlalchemy import delete, select


class ToyEmbedder:
    model_id = "test-model-1"
    dimensions = 3

    def documents(self, texts):
        return [[1.0, 0.0, 0.0] if "徒步" in text else [0.0, 1.0, 0.0] for text in texts]

    def query(self, text):
        return [1.0, 0.0, 0.0]


def test_dense_recall_obeys_scope_revision_and_deletion(system):
    app, _, a, b = system
    hybrid = create_app(app.state.settings, embedder=ToyEmbedder())
    with TestClient(hybrid) as client:
        item = client.post("/v1/memories", headers=a, json={"content": "我喜欢徒步"}).json()
        client.post("/v1/memories", headers=b, json={"content": "私人徒步地点"})
        client.post(
            "/v1/memories", headers=a, json={"content": "角色专属徒步", "character_id": "private"}
        )
        client.post(
            "/v1/memories", headers=a, json={"content": "过期徒步", "expires_at": time.time() - 1}
        )
        drain(hybrid)
        result = client.get("/v1/memories?query=户外运动", headers=a).json()
        assert result["mode"] == "hybrid"
        assert [m["id"] for m in result["items"]] == [item["id"]]
        client.patch(
            f"/v1/memories/{item['id']}", headers=a, json={"revision": 1, "content": "我喜欢绘画"}
        )
        assert client.get("/v1/memories?query=户外运动", headers=a).json()["items"] == []
        drain(hybrid)
        assert client.get("/v1/memories?query=户外运动", headers=a).json()["items"] == []
        client.delete(f"/v1/memories/{item['id']}", headers=a)
        drain(hybrid)
        with hybrid.state.factory() as session:
            assert not list(
                session.scalars(
                    select(MemoryEmbedding).where(MemoryEmbedding.memory_id == item["id"])
                )
            )


def test_pending_and_replayed_index_jobs_cannot_restore_deleted_memory(system):
    app, _, a, _ = system
    hybrid = create_app(app.state.settings, embedder=ToyEmbedder())
    with TestClient(hybrid) as client:
        item = client.post("/v1/memories", headers=a, json={"content": "徒步"}).json()
        client.delete(f"/v1/memories/{item['id']}", headers=a)
        drain(hybrid)
        with hybrid.state.factory.begin() as session:
            task = session.scalar(select(Task).where(Task.kind == "index"))
            task.status, task.attempts = "pending", 0
        drain(hybrid)
        with hybrid.state.factory() as session:
            assert not list(session.scalars(select(MemoryEmbedding)))


def test_explicit_reindex_can_rebuild_missing_derived_data(system):
    app, _, a, _ = system
    hybrid = create_app(app.state.settings, embedder=ToyEmbedder())
    with TestClient(hybrid) as client:
        item = client.post("/v1/memories", headers=a, json={"content": "徒步"}).json()
        drain(hybrid)
        with hybrid.state.factory.begin() as session:
            session.execute(delete(MemoryEmbedding))
            queue_index(session, session.get(Memory, item["id"]), ToyEmbedder.model_id, force=True)
        drain(hybrid)
        assert (
            client.get("/v1/memories?query=户外活动", headers=a).json()["items"][0]["id"]
            == item["id"]
        )


def test_embedding_failure_uses_visible_keyword_fallback(system):
    app, _, a, _ = system

    class Broken(ToyEmbedder):
        def query(self, text):
            raise EmbeddingError("offline")

    hybrid = create_app(app.state.settings, embedder=Broken())
    with TestClient(hybrid) as client:
        client.post("/v1/memories", headers=a, json={"content": "我喜欢香菜"})
        result = client.get("/v1/memories?query=香菜", headers=a).json()
        assert result["mode"] == "keyword_fallback" and len(result["items"]) == 1


def test_remote_embedding_indices_and_dimensions_are_checked():
    settings = Settings(
        embedding_provider="compatible",
        embedding_base_url="https://embeddings.example/v1",
        embedding_dimensions=3,
    )
    model = Embedder(
        settings,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"index": 1, "embedding": [1, 2, 3]}]})
        ),
    )
    with pytest.raises(EmbeddingError):
        model.documents(["test"])


def test_deepseek_chat_url_rejected_as_embedding_service():
    with pytest.raises(ValueError, match="separate embedding"):
        Embedder(
            Settings(embedding_provider="compatible", embedding_base_url="https://api.deepseek.com")
        )


def test_edit_during_embedding_does_not_publish_stale_vector(system):
    from emotional_robot.memory import patch_memory
    from emotional_robot.schemas import MemoryPatch

    app, _, a, _ = system

    class EditDuringEmbedding(ToyEmbedder):
        def documents(self, texts):
            with app.state.factory.begin() as session:
                item = session.scalar(select(Memory).where(Memory.content == "徒步"))
                patch_memory(session, item, MemoryPatch(revision=1, content="绘画"))
            return super().documents(texts)

    hybrid = create_app(app.state.settings, embedder=EditDuringEmbedding())
    with TestClient(hybrid) as client:
        item = client.post("/v1/memories", headers=a, json={"content": "徒步"}).json()
        drain(hybrid)
        with hybrid.state.factory() as session:
            assert session.get(Memory, item["id"]).revision == 2
            assert not list(session.scalars(select(MemoryEmbedding)))
