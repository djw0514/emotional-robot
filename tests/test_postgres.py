import os

import pytest
from emotional_robot.app import create_app
from emotional_robot.config import Settings
from emotional_robot.security import issue_user
from fastapi.testclient import TestClient
from test_retrieval import ToyEmbedder


@pytest.mark.skipif(
    not os.environ.get("ROBOT_TEST_POSTGRES_URL"), reason="PostgreSQL test service not configured"
)
def test_postgres_migrations_and_native_vector_search(tmp_path):
    settings = Settings(
        database_url=os.environ["ROBOT_TEST_POSTGRES_URL"],
        provider="demo",
        demo_mode=False,
        auto_worker=False,
        deletion_ledger_path=tmp_path / "pg-deletions.sqlite",
    )
    app = create_app(settings, embedder=ToyEmbedder())
    with app.state.factory.begin() as session:
        _, token = issue_user(session, "pgvector 测试用户")
    headers = {"Authorization": "Bearer " + token}
    with TestClient(app) as client:
        item = client.post("/v1/memories", headers=headers, json={"content": "徒步"}).json()
        assert app.state.worker.run_once()
        result = client.get("/v1/memories?query=户外活动", headers=headers).json()
        assert result["mode"] == "hybrid" and result["items"][0]["id"] == item["id"]
        client.delete(f"/v1/memories/{item['id']}", headers=headers)
        assert client.get("/v1/memories?query=户外活动", headers=headers).json()["items"] == []
