import argparse
import json

import uvicorn
from sqlalchemy import select

from .backup import backup_sqlite, restore_sqlite
from .config import Settings
from .db import make_database
from .embeddings import Embedder, make_embedder
from .migrations.manager import migrate
from .models import Memory
from .retrieval import queue_index
from .security import issue_user


def main():
    parser = argparse.ArgumentParser(prog="robot")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    user = commands.add_parser("create-user")
    user.add_argument("--name", required=True)
    commands.add_parser("migrate")
    commands.add_parser("prepare-model")
    commands.add_parser("reindex")
    backup = commands.add_parser("backup")
    backup.add_argument("--output", required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--backup", required=True)
    restore.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run(
            "emotional_robot.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            access_log=False,
        )
    elif args.command == "backup":
        print(json.dumps(backup_sqlite(Settings(), args.output)))
    elif args.command == "restore":
        print(json.dumps(restore_sqlite(Settings(), args.backup, args.output)))
    elif args.command == "prepare-model":
        settings = Settings().model_copy(update={"embedding_provider": "local"})
        model = Embedder(settings, allow_download=True)
        vector = model.query("验证中文记忆模型")
        print(
            json.dumps(
                {"model": settings.embedding_model, "dimensions": len(vector), "ready": True}
            )
        )
    elif args.command in {"migrate", "reindex"}:
        settings = Settings()
        engine, factory = make_database(settings.database_url, initialize=False)
        try:
            revision = migrate(engine)
            count = 0
            if args.command == "reindex":
                embedder = make_embedder(settings)
                if not embedder:
                    raise ValueError("Enable an embedding provider before reindexing")
                with factory.begin() as session:
                    for item in session.scalars(select(Memory).where(Memory.status == "active")):
                        queue_index(session, item, embedder.model_id, force=True)
                        count += 1
            print(json.dumps({"revision": revision, "memories_considered": count}))
        finally:
            engine.dispose()
    else:
        engine, factory = make_database(Settings().database_url)
        with factory.begin() as session:
            user, token = issue_user(session, args.name)
            print(json.dumps({"user_id": user.id, "token": token}, ensure_ascii=False))
        engine.dispose()


if __name__ == "__main__":
    main()
