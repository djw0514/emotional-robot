import asyncio
import json
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select, update

from .config import Settings
from .db import make_database
from .memory import add_memory, as_memory, bump_epoch, owned, patch_memory, recall, request_deletion
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
from .providers import ProviderError, make_provider
from .schemas import ConversationInput, MemoryInput, MemoryPatch, MessageInput, SettingsPatch
from .security import seed_demo, token_digest
from .worker import Worker


def create_app(settings: Settings | None = None, provider=None):
    settings = settings or Settings()
    provider = provider or make_provider(settings)
    engine, factory = make_database(settings.database_url)
    worker = Worker(factory, provider, settings.worker_poll_seconds)

    @asynccontextmanager
    async def lifespan(_):
        if settings.demo_mode:
            with factory.begin() as session:
                seed_demo(session, settings.demo_token.get_secret_value())
        if settings.auto_worker:
            worker.start()
        yield
        worker.stop()
        engine.dispose()

    app = FastAPI(title="Emotional Robot", version="0.1.0", lifespan=lifespan)
    app.state.factory, app.state.worker, app.state.settings = factory, worker, settings
    bearer = HTTPBearer(auto_error=False)

    def authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(401, "需要登录凭据", headers={"WWW-Authenticate": "Bearer"})
        with factory() as session:
            user = session.scalar(
                select(User).where(User.token_hash == token_digest(credentials.credentials))
            )
            if not user or (user.is_demo and not settings.demo_mode):
                raise HTTPException(401, "登录凭据无效", headers={"WWW-Authenticate": "Bearer"})
            return user.id

    def lock_user(session, user_id):
        # Portable write lock, including SQLite where SELECT FOR UPDATE is ignored.
        session.execute(
            update(User).where(User.id == user_id).values(memory_epoch=User.memory_epoch)
        )

    @app.get("/healthz")
    def health():
        return {"status": "ok", "provider": settings.provider, "demo_mode": settings.demo_mode}

    @app.get("/v1/me")
    def me(user_id=Depends(authenticate)):
        with factory() as session:
            user = session.get(User, user_id)
            return {
                "id": user.id,
                "name": user.name,
                "memory_enabled": user.memory_enabled,
                "provider": settings.provider,
            }

    @app.patch("/v1/memory-settings")
    def memory_settings(body: SettingsPatch, user_id=Depends(authenticate)):
        with factory.begin() as session:
            lock_user(session, user_id)
            user = session.get(User, user_id)
            user.memory_enabled = body.memory_enabled
            bump_epoch(session, user_id)
            return {"memory_enabled": user.memory_enabled}

    @app.post("/v1/conversations", status_code=201)
    def new_conversation(body: ConversationInput, user_id=Depends(authenticate)):
        with factory.begin() as session:
            item = Conversation(user_id=user_id, **body.model_dump())
            session.add(item)
            session.flush()
            return {"id": item.id, "character_id": item.character_id, "title": item.title}

    @app.get("/v1/conversations")
    def conversations(user_id=Depends(authenticate)):
        with factory() as session:
            return [
                {"id": c.id, "title": c.title, "character_id": c.character_id}
                for c in session.scalars(
                    select(Conversation)
                    .where(Conversation.user_id == user_id)
                    .order_by(Conversation.created_at.desc())
                    .limit(100)
                )
            ]

    @app.get("/v1/conversations/{conversation_id}/messages")
    def messages(conversation_id: str, user_id=Depends(authenticate)):
        with factory() as session:
            owned(session, Conversation, conversation_id, user_id)
            rows = session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(200)
            )
            return [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content or "[内容已清除]",
                    "created_at": m.created_at,
                }
                for m in reversed(list(rows))
            ]

    @app.post("/v1/memories", status_code=201)
    def new_memory(body: MemoryInput, user_id=Depends(authenticate)):
        with factory.begin() as session:
            lock_user(session, user_id)
            return as_memory(add_memory(session, user_id, **body.model_dump()))

    @app.get("/v1/memories")
    def memories(
        character_id: str = "companion",
        status: str = Query("active", pattern="^(active|candidate|superseded|all)$"),
        query: str = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
        user_id=Depends(authenticate),
    ):
        with factory() as session:
            if query:
                return {
                    "items": recall(session, user_id, character_id, query, min(limit, 20)),
                    "offset": 0,
                }
            stmt = select(Memory).where(
                Memory.user_id == user_id,
                Memory.character_id == character_id,
                Memory.status != "deleted",
            )
            if status != "all":
                stmt = stmt.where(Memory.status == status)
            rows = session.scalars(
                stmt.order_by(Memory.pinned.desc(), Memory.updated_at.desc())
                .offset(offset)
                .limit(limit)
            )
            return {"items": [as_memory(m) for m in rows], "offset": offset}

    @app.get("/v1/memories/{memory_id}")
    def memory_detail(memory_id: str, user_id=Depends(authenticate)):
        with factory() as session:
            item = owned(session, Memory, memory_id, user_id)
            if item.status == "deleted":
                raise HTTPException(404, "资源不存在")
            result = as_memory(item)
            result["versions"] = [
                {
                    "revision": v.revision,
                    "content": v.content,
                    "reason": v.reason,
                    "created_at": v.created_at,
                }
                for v in session.scalars(
                    select(MemoryVersion)
                    .where(MemoryVersion.memory_id == item.id)
                    .order_by(MemoryVersion.revision)
                )
            ]
            result["evidence"] = [
                {
                    "id": m.id,
                    "content": m.content or "[来源已清除]",
                    "conversation_id": m.conversation_id,
                }
                for m in session.scalars(
                    select(Message)
                    .join(MemoryEvidence, MemoryEvidence.message_id == Message.id)
                    .where(MemoryEvidence.memory_id == item.id, Message.user_id == user_id)
                )
            ]
            return result

    @app.patch("/v1/memories/{memory_id}")
    def edit_memory(memory_id: str, body: MemoryPatch, user_id=Depends(authenticate)):
        with factory.begin() as session:
            lock_user(session, user_id)
            return as_memory(
                patch_memory(session, owned(session, Memory, memory_id, user_id), body)
            )

    @app.delete("/v1/memories/{memory_id}", status_code=202)
    def delete_memory(memory_id: str, user_id=Depends(authenticate)):
        with factory.begin() as session:
            lock_user(session, user_id)
            task = request_deletion(session, owned(session, Memory, memory_id, user_id))
            return {
                "id": task.id,
                "status": task.status,
                "affected_memory_count": len(task.payload["memory_ids"]),
            }

    @app.get("/v1/deletion-jobs/{job_id}")
    def deletion_job(job_id: str, user_id=Depends(authenticate)):
        with factory() as session:
            task = owned(session, Task, job_id, user_id)
            if task.kind != "delete":
                raise HTTPException(404, "资源不存在")
            return {
                "id": task.id,
                "status": task.status,
                "scope": "online_database",
                "error_code": task.error_code,
            }

    @app.get("/v1/tasks")
    def tasks(user_id=Depends(authenticate)):
        with factory() as session:
            return [
                {
                    "id": t.id,
                    "kind": t.kind,
                    "status": t.status,
                    "attempts": t.attempts,
                    "error_code": t.error_code,
                }
                for t in session.scalars(
                    select(Task)
                    .where(Task.user_id == user_id)
                    .order_by(Task.created_at.desc())
                    .limit(100)
                )
            ]

    @app.get("/v1/memory-export")
    def export(user_id=Depends(authenticate)):
        with factory() as session:
            return {
                "format_version": 1,
                "memories": [
                    as_memory(m)
                    for m in session.scalars(
                        select(Memory).where(Memory.user_id == user_id, Memory.status != "deleted")
                    )
                ],
            }

    @app.post("/v1/tasks/{task_id}/retry")
    def retry_task(task_id: str, user_id=Depends(authenticate)):
        with factory.begin() as session:
            lock_user(session, user_id)
            task = owned(session, Task, task_id, user_id)
            if task.status != "failed":
                raise HTTPException(409, "仅失败任务可以重试")
            task.status, task.attempts, task.available_at, task.error_code = "pending", 0, 0, None
            return {"id": task.id, "status": task.status}

    @app.post("/v1/conversations/{conversation_id}/messages")
    def chat(conversation_id: str, body: MessageInput, user_id=Depends(authenticate)):
        with factory.begin() as session:
            lock_user(session, user_id)
            conversation = owned(session, Conversation, conversation_id, user_id)
            user = session.get(User, user_id)
            run = session.scalar(
                select(ChatRun).where(
                    ChatRun.conversation_id == conversation_id, ChatRun.client_id == body.client_id
                )
            )
            replay = False
            if run:
                source = session.get(Message, run.user_message_id)
                if source.content != body.content:
                    raise HTTPException(409, "此请求编号已用于其他消息")
                if run.status != "completed" or run.memory_epoch != user.memory_epoch:
                    raise HTTPException(409, "此请求进行中、已中断或记忆已变化，请刷新后重新发送")
                replay = True
            else:
                # Runs lost to disconnects or crashes cannot block a conversation forever.
                session.execute(
                    update(ChatRun)
                    .where(
                        ChatRun.conversation_id == conversation_id,
                        ChatRun.status == "running",
                        ChatRun.created_at < time.time() - 180,
                    )
                    .values(status="interrupted")
                )
                if session.scalar(
                    select(func.count())
                    .select_from(ChatRun)
                    .where(ChatRun.conversation_id == conversation_id, ChatRun.status == "running")
                ):
                    raise HTTPException(409, "请等待当前回复结束或取消后再发送")
                message = Message(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    client_id=body.client_id,
                    role="user",
                    content=body.content,
                    memory_allowed=body.remember and user.memory_enabled,
                )
                session.add(message)
                session.flush()
                if message.memory_allowed:
                    session.add(
                        Task(
                            user_id=user_id,
                            kind="extract",
                            dedupe_key=message.id,
                            payload={
                                "message_id": message.id,
                                "requires_confirmation": settings.provider != "demo",
                            },
                        )
                    )
                run = ChatRun(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    client_id=body.client_id,
                    user_message_id=message.id,
                    status="running",
                    memory_epoch=user.memory_epoch,
                )
                session.add(run)
                session.flush()
            run_id, epoch, saved_content = run.id, run.memory_epoch, run.content
            memory_rows = (
                [
                    as_memory(m)
                    for m in session.scalars(
                        select(Memory).where(
                            Memory.id.in_(run.memory_ids),
                            Memory.user_id == user_id,
                            Memory.status == "active",
                        )
                    )
                ]
                if replay
                else recall(session, user_id, conversation.character_id, body.content)
            )
            memory_refs = [
                {"id": m["id"], "content": m["content"], "revision": m["revision"]}
                for m in memory_rows
            ]
            history = list(
                session.scalars(
                    select(Message)
                    .where(
                        Message.conversation_id == conversation_id,
                        Message.context_allowed.is_(True),
                    )
                    .order_by(Message.created_at.desc())
                    .limit(20)
                )
            )
            history.reverse()
            # Bound recent context by characters; exact tokenizer budgeting is a later stage.
            recent, budget = [], 0
            for message in reversed(history):
                if budget + len(message.content) > 12000:
                    break
                recent.append({"role": message.role, "content": message.content})
                budget += len(message.content)
            recent.reverse()

        def valid():
            with factory() as session:
                return session.get(User, user_id).memory_epoch == epoch

        def finish(status, content=""):
            with factory.begin() as session:
                lock_user(session, user_id)
                current = session.get(ChatRun, run_id)
                if current.status != "running":
                    return False
                if session.get(User, user_id).memory_epoch != epoch:
                    current.status = "invalidated"
                    return False
                current.status, current.content = status, content
                if status == "completed":
                    current.memory_ids = [m["id"] for m in memory_refs]
                    session.add(
                        Message(
                            conversation_id=conversation_id,
                            user_id=user_id,
                            role="assistant",
                            content=content,
                            memory_allowed=False,
                        )
                    )
                return True

        async def events():
            sequence = 0

            def encode(event, data):
                nonlocal sequence
                sequence += 1
                payload = {"request_id": run_id, "sequence": sequence, **data}
                return f"id: {run_id}:{sequence}\nevent: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

            yield encode("accepted", {"replayed": replay})
            output = []
            try:
                if replay:
                    if not valid():
                        raise ProviderError("context_changed")
                    yield encode("token", {"text": saved_content})
                else:
                    async for token in provider.stream(recent, memory_refs):
                        if not valid():
                            raise ProviderError("context_changed")
                        output.append(token)
                        yield encode("token", {"text": token})
                    if not finish("completed", "".join(output)):
                        raise ProviderError("context_changed")
                yield encode("completed", {"memory_ids": [m["id"] for m in memory_refs]})
            except asyncio.CancelledError:
                if not replay:
                    finish("cancelled")
                raise
            except Exception:
                if not replay:
                    finish("failed")
                yield encode(
                    "error",
                    {
                        "code": "response_interrupted",
                        "message": "回复中断，请检查连接或刷新记忆后重试。",
                    },
                )

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
