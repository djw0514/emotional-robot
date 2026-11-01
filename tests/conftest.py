import pytest
from emotional_robot.app import create_app
from emotional_robot.config import Settings
from emotional_robot.security import issue_user
from fastapi.testclient import TestClient


@pytest.fixture
def system(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}", auto_worker=False, demo_mode=False
    )
    app = create_app(settings)
    with app.state.factory.begin() as session:
        _, token_a = issue_user(session, "用户甲")
        _, token_b = issue_user(session, "用户乙")
    with TestClient(app) as client:
        yield (
            app,
            client,
            {"Authorization": f"Bearer {token_a}"},
            {"Authorization": f"Bearer {token_b}"},
        )


def conversation(client, headers, character_id="companion"):
    response = client.post(
        "/v1/conversations", headers=headers, json={"character_id": character_id}
    )
    assert response.status_code == 201
    return response.json()["id"]


def send(client, headers, conversation_id, content, client_id="message-1", **kwargs):
    response = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": content, "client_id": client_id, **kwargs},
    )
    return response


def drain(app):
    for _ in range(30):
        if not app.state.worker.run_once():
            return
    raise AssertionError("Worker did not drain")
