from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConversationInput(Input):
    character_id: str = Field(default="companion", min_length=1, max_length=80)
    title: str = Field(default="新对话", min_length=1, max_length=100)


class MessageInput(Input):
    content: str = Field(min_length=1, max_length=8000)
    client_id: str = Field(min_length=1, max_length=100)
    remember: bool = True


class MemoryInput(Input):
    content: str = Field(min_length=1, max_length=2000)
    character_id: str = Field(default="companion", min_length=1, max_length=80)
    kind: Literal["fact", "preference", "event"] = "fact"
    pinned: bool = False
    expires_at: float | None = Field(default=None, gt=0)


class MemoryPatch(Input):
    revision: int = Field(ge=1)
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    pinned: bool | None = None
    status: Literal["active", "candidate"] | None = None
    reason: Literal["correction", "change", "confirmation"] = "correction"


class SettingsPatch(Input):
    memory_enabled: bool


class ExtractedFact(Input):
    content: str = Field(min_length=1, max_length=500)
    predicate: str = Field(min_length=1, max_length=80)
    kind: Literal["fact", "preference", "event"] = "fact"
    evidence: str = Field(min_length=1, max_length=8000)

    @field_validator("predicate")
    @classmethod
    def safe_predicate(cls, value: str) -> str:
        if any(c in value for c in "\n\r\t"):
            raise ValueError("Invalid predicate")
        return value
