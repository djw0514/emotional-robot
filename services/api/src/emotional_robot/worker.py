import threading
import time

from sqlalchemy import and_, case, or_, select, update

from .memory import extraction_result, purge_deleted
from .models import Message, Task, User


class Worker:
    def __init__(self, factory, provider, interval: float = 0.5):
        self.factory, self.provider, self.interval = factory, provider, interval
        self.stop_event = threading.Event()
        self.thread = None

    def run_once(self) -> bool:
        now = time.time()
        eligible = and_(
            Task.attempts < 3,
            or_(
                and_(Task.status == "pending", Task.available_at <= now),
                and_(Task.status == "running", Task.lease_until < now),
            ),
        )
        with self.factory.begin() as session:
            session.execute(
                update(Task)
                .where(Task.status == "running", Task.attempts >= 3, Task.lease_until < now)
                .values(status="failed", error_code="lease_exhausted", lease_until=0)
            )
            task_id = session.scalar(
                select(Task.id)
                .where(eligible)
                .order_by(case((Task.kind == "delete", 0), else_=1), Task.created_at)
                .limit(1)
            )
            if not task_id:
                return False
            result = session.execute(
                update(Task)
                .where(Task.id == task_id, eligible)
                .values(status="running", attempts=Task.attempts + 1, lease_until=now + 120)
            )
            if result.rowcount != 1:
                return True
            task = session.get(Task, task_id)
            attempt = task.attempts
            payload, kind = task.payload, task.kind
        try:
            facts = []
            if kind == "extract":
                with self.factory() as session:
                    message = session.get(Message, payload["message_id"])
                    source = message.content if message and message.memory_allowed else ""
                if source:
                    facts = self.provider.extract(source)
            with self.factory.begin() as session:
                # A new lease holder must not be overwritten by a stale worker.
                ownership = session.execute(
                    update(Task)
                    .where(
                        Task.id == task_id,
                        Task.status == "running",
                        Task.attempts == attempt,
                    )
                    .values(lease_until=time.time() + 120)
                )
                if ownership.rowcount != 1:
                    return True
                task = session.get(Task, task_id)
                session.execute(
                    update(User)
                    .where(User.id == task.user_id)
                    .values(memory_epoch=User.memory_epoch)
                )
                if kind == "delete":
                    purge_deleted(session, task)
                else:
                    extraction_result(session, task, facts)
                task.status, task.lease_until, task.error_code = "completed", 0, None
        except Exception:
            with self.factory.begin() as session:
                session.execute(
                    update(Task)
                    .where(
                        Task.id == task_id,
                        Task.status == "running",
                        Task.attempts == attempt,
                    )
                    .values(
                        status="failed" if attempt >= 3 else "pending",
                        lease_until=0,
                        available_at=time.time() + min(60, 2**attempt),
                        error_code="processing_failed",
                    )
                )
        return True

    def start(self):
        def loop():
            while not self.stop_event.is_set():
                try:
                    worked = self.run_once()
                except Exception:
                    worked = False
                self.stop_event.wait(self.interval if not worked else min(self.interval, 0.1))

        self.thread = threading.Thread(target=loop, name="memory-worker", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
