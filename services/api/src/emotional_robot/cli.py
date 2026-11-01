import argparse
import json

import uvicorn

from .config import Settings
from .db import make_database
from .security import issue_user


def main():
    parser = argparse.ArgumentParser(prog="robot")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    user = commands.add_parser("create-user")
    user.add_argument("--name", required=True)
    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run(
            "emotional_robot.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            access_log=False,
        )
    else:
        engine, factory = make_database(Settings().database_url)
        with factory.begin() as session:
            user, token = issue_user(session, args.name)
            print(json.dumps({"user_id": user.id, "token": token}, ensure_ascii=False))
        engine.dispose()


if __name__ == "__main__":
    main()
