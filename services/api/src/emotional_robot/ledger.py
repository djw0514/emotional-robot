"""Durable deletion journal kept outside the application database and its snapshots."""

import json
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

from sqlalchemy import delete, select, update

from .models import (
    ChatRun,
    DeletionReceipt,
    Memory,
    MemoryEmbedding,
    MemoryEvidence,
    MemoryVersion,
    Message,
    User,
)


class DeletionLedger:
    def __init__(self, path):
        self.path = Path(path)

    def ensure(self):
        self.path.resolve().parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=30)) as db, db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS deletions (id TEXT PRIMARY KEY, created_at REAL NOT NULL, payload TEXT NOT NULL)"
            )
            db.execute(
                "INSERT OR IGNORE INTO metadata VALUES ('identity', ?)", (str(uuid.uuid4()),)
            )
            return db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()[0]

    def identity(self):
        if not self.path.is_file():
            raise RuntimeError("The original deletion ledger is required for restore")
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            return db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()[0]

    def record(self, user_id, memory_ids, source_ids):
        self.ensure()
        event = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "memory_ids": sorted(memory_ids),
            "source_message_ids": sorted(source_ids),
        }
        with closing(sqlite3.connect(self.path, timeout=30)) as db, db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute(
                "INSERT INTO deletions VALUES (?, ?, ?)",
                (event["id"], time.time(), json.dumps(event)),
            )
        return event["id"]

    def events(self):
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            return [
                json.loads(row[0])
                for row in db.execute("SELECT payload FROM deletions ORDER BY created_at, id")
            ]


def replay_deletions(factory, ledger):
    applied = 0
    for event in ledger.events():
        with factory.begin() as session:
            user_id = event["user_id"]
            if (
                session.execute(
                    update(User).where(User.id == user_id).values(memory_epoch=User.memory_epoch)
                ).rowcount
                != 1
            ):
                continue
            ids = event["memory_ids"]
            if session.scalar(
                select(Memory.id).where(Memory.id.in_(ids), Memory.user_id != user_id)
            ):
                raise RuntimeError("Deletion journal ownership mismatch")
            fresh = session.get(DeletionReceipt, event["id"]) is None
            session.execute(
                update(Memory)
                .where(Memory.id.in_(ids), Memory.user_id == user_id, Memory.status != "deleted")
                .values(status="deleted", revision=Memory.revision + 1)
            )
            session.execute(
                update(Memory)
                .where(Memory.id.in_(ids), Memory.user_id == user_id)
                .values(content="", source_message_id=None, pinned=False)
            )
            session.execute(delete(MemoryVersion).where(MemoryVersion.memory_id.in_(ids)))
            session.execute(delete(MemoryEmbedding).where(MemoryEmbedding.memory_id.in_(ids)))
            session.execute(delete(MemoryEvidence).where(MemoryEvidence.memory_id.in_(ids)))
            session.execute(
                update(Message)
                .where(Message.id.in_(event["source_message_ids"]), Message.user_id == user_id)
                .values(content="", memory_allowed=False, context_allowed=False)
            )
            if fresh:
                session.execute(
                    update(ChatRun)
                    .where(ChatRun.user_id == user_id)
                    .values(content="", memory_ids=[], status="invalidated")
                )
                session.execute(
                    update(Message)
                    .where(Message.user_id == user_id, Message.role == "assistant")
                    .values(content="", context_allowed=False)
                )
                session.execute(
                    update(User)
                    .where(User.id == user_id)
                    .values(memory_epoch=User.memory_epoch + 1)
                )
                session.add(DeletionReceipt(id=event["id"], user_id=user_id))
                applied += 1
    return applied
