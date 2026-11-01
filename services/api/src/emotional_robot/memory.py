import re
import time

from fastapi import HTTPException
from sqlalchemy import delete, or_, select, update

from .models import (
    ChatRun,
    Conversation,
    Memory,
    MemoryEvidence,
    MemoryVersion,
    Message,
    Task,
    User,
)


def owned(session, model, item_id: str, user_id: str):
    item = session.scalar(select(model).where(model.id == item_id, model.user_id == user_id))
    if item is None:
        raise HTTPException(404, "资源不存在")
    return item


def bump_epoch(session, user_id: str):
    session.execute(
        update(User).where(User.id == user_id).values(memory_epoch=User.memory_epoch + 1)
    )


def as_memory(item: Memory) -> dict:
    return {
        name: getattr(item, name)
        for name in (
            "id",
            "character_id",
            "kind",
            "predicate",
            "content",
            "status",
            "revision",
            "pinned",
            "source_type",
            "source_message_id",
            "expires_at",
            "created_at",
            "updated_at",
        )
    }


def usable_memories(session, user_id: str, character_id: str):
    return list(
        session.scalars(
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.character_id == character_id,
                Memory.status == "active",
                or_(Memory.expires_at.is_(None), Memory.expires_at > time.time()),
            )
            .order_by(Memory.updated_at.desc(), Memory.id)
        )
    )


def terms(text: str) -> set[str]:
    result = set(re.findall(r"[a-z0-9]+", text.lower()))
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        result.update(segment[n : n + 2] for n in range(max(1, len(segment) - 1)))
    return result


def recall(session, user_id: str, character_id: str, query: str, limit: int = 6) -> list[dict]:
    query_terms = terms(query)
    scored = []
    predicates = []
    if any(word in query for word in ("名字", "叫什么", "称呼", "叫我")):
        predicates.append("preferred_name")
    if any(word in query for word in ("住哪", "住在", "居住")):
        predicates.append("residence")
    for item in usable_memories(session, user_id, character_id):
        overlap = len(query_terms & terms(item.content))
        score = overlap + (8 if item.predicate in predicates else 0) + (2 if item.pinned else 0)
        if score > 0:
            scored.append((score, item.updated_at, item))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    result, budget = [], 0
    for _, _, item in scored[:limit]:
        if budget + len(item.content) > 3000:
            continue
        result.append(as_memory(item))
        budget += len(item.content)
    return result


def add_memory(
    session,
    user_id: str,
    *,
    content: str,
    character_id: str = "companion",
    kind: str = "fact",
    pinned: bool = False,
    expires_at=None,
    predicate: str = "note",
    source_message_id=None,
    status="active",
) -> Memory:
    item = Memory(
        user_id=user_id,
        content=content,
        character_id=character_id,
        kind=kind,
        pinned=pinned,
        expires_at=expires_at,
        predicate=predicate,
        source_message_id=source_message_id,
        source_type="user_statement" if source_message_id else "manual",
        status=status,
    )
    session.add(item)
    session.flush()
    session.add(MemoryVersion(memory_id=item.id, revision=1, content=content, reason="created"))
    if source_message_id:
        session.add(MemoryEvidence(memory_id=item.id, message_id=source_message_id))
    session.flush()
    return item


def patch_memory(session, item: Memory, patch) -> Memory:
    if item.status == "deleted":
        raise HTTPException(404, "资源不存在")
    values = {"revision": item.revision + 1, "updated_at": time.time()}
    if patch.content is not None:
        values["content"] = patch.content
    if patch.pinned is not None:
        values["pinned"] = patch.pinned
    if patch.status is not None:
        values["status"] = patch.status
    result = session.execute(
        update(Memory)
        .where(
            Memory.id == item.id,
            Memory.revision == patch.revision,
            Memory.status != "deleted",
        )
        .values(**values),
        execution_options={"synchronize_session": False},
    )
    if result.rowcount != 1:
        raise HTTPException(409, "记忆已更新，请刷新后重试")
    if patch.status == "active" and item.predicate != "note":
        previous = list(
            session.scalars(
                select(Memory).where(
                    Memory.user_id == item.user_id,
                    Memory.character_id == item.character_id,
                    Memory.predicate == item.predicate,
                    Memory.id != item.id,
                    Memory.status == "active",
                )
            )
        )
        for old in previous:
            old.status, old.revision, old.updated_at = "superseded", old.revision + 1, time.time()
            session.add(
                MemoryVersion(
                    memory_id=old.id,
                    revision=old.revision,
                    content=old.content,
                    reason="superseded",
                )
            )
            old_sources = select(MemoryEvidence.message_id).where(
                MemoryEvidence.memory_id == old.id
            )
            session.execute(
                update(Message)
                .where(Message.id.in_(old_sources))
                .values(memory_allowed=False, context_allowed=False)
            )
            # Existing assistant echoes must not reintroduce the old fact into context.
            session.execute(
                update(Message)
                .where(Message.user_id == item.user_id, Message.role == "assistant")
                .values(context_allowed=False)
            )
    if patch.content is not None:
        source_ids = list(
            session.scalars(
                select(MemoryEvidence.message_id).where(MemoryEvidence.memory_id == item.id)
            )
        )
        if source_ids:
            source_conversations = select(Message.conversation_id).where(Message.id.in_(source_ids))
            conversation_ids = list(session.scalars(source_conversations))
            session.execute(
                update(Message)
                .where(Message.id.in_(source_ids))
                .values(memory_allowed=False, context_allowed=False)
            )
            session.execute(
                update(Message)
                .where(Message.conversation_id.in_(conversation_ids), Message.role == "assistant")
                .values(context_allowed=False)
            )
    session.expire(item)
    session.refresh(item)
    session.add(
        MemoryVersion(
            memory_id=item.id, revision=item.revision, content=item.content, reason=patch.reason
        )
    )
    bump_epoch(session, item.user_id)
    session.flush()
    return item


def request_deletion(session, item: Memory) -> Task:
    existing = session.scalar(
        select(Task).where(
            Task.user_id == item.user_id, Task.kind == "delete", Task.dedupe_key == item.id
        )
    )
    if existing:
        return existing
    source_ids = set(
        session.scalars(
            select(MemoryEvidence.message_id).where(MemoryEvidence.memory_id == item.id)
        )
    )
    if item.source_message_id:
        source_ids.add(item.source_message_id)
    # Delete the whole source message, including any memories derived from that message.
    affected = {item.id}
    while source_ids:
        old_size = (len(affected), len(source_ids))
        affected.update(
            session.scalars(
                select(MemoryEvidence.memory_id).where(MemoryEvidence.message_id.in_(source_ids))
            )
        )
        source_ids.update(
            session.scalars(
                select(MemoryEvidence.message_id).where(MemoryEvidence.memory_id.in_(affected))
            )
        )
        if old_size == (len(affected), len(source_ids)):
            break
    ids = list(affected)
    session.execute(
        update(Memory)
        .where(Memory.id.in_(ids), Memory.user_id == item.user_id)
        .values(status="deleted", revision=Memory.revision + 1, updated_at=time.time())
    )
    conversation_ids = list(
        session.scalars(select(Message.conversation_id).where(Message.id.in_(source_ids)))
    )
    if source_ids:
        session.execute(
            update(Message)
            .where(Message.id.in_(source_ids), Message.user_id == item.user_id)
            .values(memory_allowed=False, context_allowed=False, content="")
        )
    # Cached generations can contain remembered facts even in another conversation.
    session.execute(
        update(ChatRun)
        .where(ChatRun.user_id == item.user_id)
        .values(content="", status="invalidated", memory_ids=[])
    )
    session.execute(
        update(Message)
        .where(Message.user_id == item.user_id, Message.role == "assistant")
        .values(content="", context_allowed=False)
    )
    bump_epoch(session, item.user_id)
    task = Task(
        user_id=item.user_id,
        kind="delete",
        dedupe_key=item.id,
        payload={
            "memory_ids": ids,
            "source_message_ids": list(source_ids),
            "conversation_ids": conversation_ids,
        },
    )
    session.add(task)
    session.flush()
    return task


def purge_deleted(session, task: Task):
    ids = task.payload["memory_ids"]
    session.execute(
        update(Memory)
        .where(Memory.id.in_(ids), Memory.user_id == task.user_id, Memory.status == "deleted")
        .values(content="", source_message_id=None, pinned=False)
    )
    session.execute(delete(MemoryVersion).where(MemoryVersion.memory_id.in_(ids)))
    session.execute(delete(MemoryEvidence).where(MemoryEvidence.memory_id.in_(ids)))


def extraction_result(session, task: Task, facts: list):
    message = owned(session, Message, task.payload["message_id"], task.user_id)
    user = session.get(User, task.user_id)
    if not message.memory_allowed or not message.content or not user.memory_enabled:
        return
    conversation = owned(session, Conversation, message.conversation_id, task.user_id)
    for fact in facts:
        if fact.evidence not in message.content:
            continue
        duplicate = session.scalar(
            select(Memory).where(
                Memory.user_id == task.user_id,
                Memory.character_id == conversation.character_id,
                Memory.content == fact.content,
                Memory.status.in_(["active", "candidate"]),
            )
        )
        if duplicate:
            evidence = session.scalar(
                select(MemoryEvidence).where(
                    MemoryEvidence.memory_id == duplicate.id,
                    MemoryEvidence.message_id == message.id,
                )
            )
            if evidence is None:
                session.add(MemoryEvidence(memory_id=duplicate.id, message_id=message.id))
            continue
        # A conflicting slot becomes a candidate. Only the user can confirm replacement.
        conflict = session.scalar(
            select(Memory).where(
                Memory.user_id == task.user_id,
                Memory.character_id == conversation.character_id,
                Memory.predicate == fact.predicate,
                Memory.status == "active",
            )
        )
        add_memory(
            session,
            task.user_id,
            content=fact.content,
            kind=fact.kind,
            character_id=conversation.character_id,
            predicate=fact.predicate,
            source_message_id=message.id,
            status="candidate"
            if conflict or task.payload.get("requires_confirmation", True)
            else "active",
        )
