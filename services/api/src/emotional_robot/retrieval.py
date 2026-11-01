import hashlib
import math
import time

from sqlalchemy import or_, select

from .models import Memory, MemoryEmbedding, Task


def queue_index(session, memory, model_id, *, force=False):
    if not model_id or memory.status != "active":
        return
    key = hashlib.sha256(f"{memory.id}:{memory.revision}:{model_id}".encode()).hexdigest()
    existing = session.scalar(
        select(Task).where(
            Task.user_id == memory.user_id, Task.kind == "index", Task.dedupe_key == key
        )
    )
    if existing:
        if force and existing.status != "running":
            existing.status, existing.attempts, existing.available_at = "pending", 0, 0
            existing.error_code = None
        return
    session.add(
        Task(
            user_id=memory.user_id,
            kind="index",
            dedupe_key=key,
            payload={"memory_id": memory.id, "revision": memory.revision, "model_id": model_id},
        )
    )


def save_embedding(session, task, vector, embedder):
    item = session.get(Memory, task.payload["memory_id"])
    if (
        not item
        or item.user_id != task.user_id
        or item.status != "active"
        or item.revision != task.payload["revision"]
        or task.payload["model_id"] != embedder.model_id
    ):
        return
    existing = session.scalar(
        select(MemoryEmbedding).where(
            MemoryEmbedding.memory_id == item.id, MemoryEmbedding.model_id == embedder.model_id
        )
    )
    if existing:
        existing.revision, existing.embedding, existing.dimensions = (
            item.revision,
            vector,
            embedder.dimensions,
        )
    else:
        session.add(
            MemoryEmbedding(
                memory_id=item.id,
                revision=item.revision,
                model_id=embedder.model_id,
                dimensions=embedder.dimensions,
                embedding=vector,
            )
        )


class Retriever:
    def __init__(self, embedder=None, threshold=0.35):
        self.embedder, self.threshold = embedder, threshold

    @property
    def model_id(self):
        return self.embedder.model_id if self.embedder else None

    def prepare(self, query):
        if self.embedder is None:
            return None
        try:
            return self.embedder.query(query)
        except Exception:
            return None

    def search(self, session, user_id, character_id, query, limit=6, *, vector=None):
        from .memory import as_memory, recall

        lexical = recall(session, user_id, character_id, query, max(limit, 30))
        if self.embedder is None or vector is None:
            return {
                "items": lexical[:limit],
                "mode": "keyword" if self.embedder is None else "keyword_fallback",
            }
        stmt = (
            select(Memory, MemoryEmbedding)
            .join(MemoryEmbedding, MemoryEmbedding.memory_id == Memory.id)
            .where(
                Memory.user_id == user_id,
                Memory.character_id == character_id,
                Memory.status == "active",
                or_(Memory.expires_at.is_(None), Memory.expires_at > time.time()),
                MemoryEmbedding.revision == Memory.revision,
                MemoryEmbedding.model_id == self.model_id,
                MemoryEmbedding.dimensions == self.embedder.dimensions,
            )
        )
        dense = []
        if session.bind.dialect.name == "postgresql":
            distance = MemoryEmbedding.embedding.cosine_distance(vector)
            for item, _, value in session.execute(
                stmt.add_columns(distance)
                .where(distance <= 1 - self.threshold)
                .order_by(distance)
                .limit(30)
            ):
                dense.append((1 - float(value), as_memory(item)))
        else:
            for item, embedding in session.execute(stmt):
                values = embedding.embedding
                norm = math.sqrt(sum(float(x) ** 2 for x in values))
                score = (
                    sum(a * b for a, b in zip(vector, values, strict=True)) / norm if norm else 0
                )
                if score >= self.threshold:
                    dense.append((score, as_memory(item)))
            dense.sort(key=lambda row: (-row[0], row[1]["id"]))
            dense = dense[:30]
        # Keep semantic relevance dominant; generic Chinese word overlap is a weak signal.
        # Rank fusion with equal weights let incidental word matches swamp strong dense hits.
        scores = {item["id"]: 0.02 / rank for rank, item in enumerate(lexical, 1)}
        by_id = {item["id"]: item for item in lexical}
        for score, item in dense:
            by_id[item["id"]] = item
            scores[item["id"]] = score + scores.get(item["id"], 0)
        ranked = sorted(scores, key=lambda mid: (-scores[mid], mid))
        result, budget = [], 0
        for mid in ranked:
            item = by_id[mid]
            if budget + len(item["content"]) > 3000:
                continue
            result.append(item)
            budget += len(item["content"])
            if len(result) == limit:
                break
        return {"items": result, "mode": "hybrid", "indexed_candidates": len(dense)}
