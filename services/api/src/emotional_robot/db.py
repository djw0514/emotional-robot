from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .migrations.manager import migrate


def make_database(url: str, *, initialize=True):
    parsed = make_url(url)
    options = {"pool_pre_ping": True}
    if parsed.get_backend_name() == "sqlite":
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if parsed.database in (None, "", ":memory:"):
            options["poolclass"] = StaticPool
        else:
            Path(parsed.database).resolve().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **options)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def sqlite_options(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    if initialize:
        migrate(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
