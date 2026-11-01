from emotional_robot.app import create_app
from emotional_robot.config import Settings
from fastapi.testclient import TestClient


def test_disabling_demo_rejects_persisted_demo_account(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'demo.db'}", auto_worker=False, demo_mode=True
    )
    headers = {"Authorization": "Bearer " + settings.demo_token.get_secret_value()}
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/me", headers=headers).status_code == 200
    with TestClient(create_app(settings.model_copy(update={"demo_mode": False}))) as client:
        assert client.get("/v1/me", headers=headers).status_code == 401
