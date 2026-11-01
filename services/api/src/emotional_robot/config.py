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
