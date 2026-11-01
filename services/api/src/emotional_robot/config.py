from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROBOT_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/private/robot.db"
    demo_mode: bool = True
    demo_token: SecretStr = SecretStr("local-demo-change-me")
    provider: Literal["demo", "compatible"] = "demo"
    model_base_url: str = "https://api.deepseek.com"
    model_name: str = "deepseek-flash"
    model_api_key: SecretStr = SecretStr("")
    auto_worker: bool = True
    worker_poll_seconds: float = 0.5
    model_timeout_seconds: float = 45
    embedding_provider: Literal["none", "local", "compatible"] = "none"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_version: str = "1"
    embedding_dimensions: int = 512
    embedding_base_url: str = ""
    embedding_api_key: SecretStr = SecretStr("")
    embedding_cache_dir: Path = Path("data/private/models")
    semantic_min_score: float = 0.35
    deletion_ledger_path: Path = Path("data/private/deletion-ledger.sqlite")
