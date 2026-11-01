import time
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def identifier() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    name: Mapped[str] = mapped_column(String(80))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    memory_epoch: Mapped[int] = mapped_column(Integer, default=0)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    character_id: Mapped[str] = mapped_column(String(80), default="companion")
    title: Mapped[str] = mapped_column(String(100), default="新对话")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "client_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    client_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(String(12))
    content: Mapped[str] = mapped_column(Text)
    memory_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    context_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (Index("ix_memory_scope", "user_id", "character_id", "status"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    character_id: Mapped[str] = mapped_column(String(80), default="companion")
    kind: Mapped[str] = mapped_column(String(20), default="fact")
    predicate: Mapped[str] = mapped_column(String(80), default="note")
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    source_type: Mapped[str] = mapped_column(String(30), default="manual")
    source_message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    expires_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class MemoryVersion(Base):
    __tablename__ = "memory_versions"
    __table_args__ = (UniqueConstraint("memory_id", "revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class MemoryEvidence(Base):
    __tablename__ = "memory_evidence"
    __table_args__ = (UniqueConstraint("memory_id", "message_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id"), index=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), index=True)


class Task(Base):
    __tablename__ = "memory_tasks"
    __table_args__ = (UniqueConstraint("user_id", "kind", "dedupe_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    dedupe_key: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    available_at: Mapped[float] = mapped_column(Float, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class ChatRun(Base):
    __tablename__ = "chat_runs"
    __table_args__ = (UniqueConstraint("conversation_id", "client_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    client_id: Mapped[str] = mapped_column(String(100))
    user_message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    memory_epoch: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, default="")
    memory_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class MemoryEmbedding(Base):
    __tablename__ = "memory_embeddings"
    __table_args__ = (UniqueConstraint("memory_id", "model_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    model_id: Mapped[str] = mapped_column(String(64), index=True)
    dimensions: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list] = mapped_column(Vector().with_variant(JSON, "sqlite"))


class DeletionReceipt(Base):
    __tablename__ = "deletion_receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    applied_at: Mapped[float] = mapped_column(Float, default=time.time)
