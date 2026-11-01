from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from .legacy import LEGACY_COLUMNS


def config_for(connection):
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent))
    config.attributes["connection"] = connection
    return config


def migrate(engine, revision="head"):
    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        elif engine.dialect.name == "postgresql":
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(716203119)")
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        if tables and "alembic_version" not in tables:
            # Never guess the version of a database with an unknown or partial schema.
            if tables != set(LEGACY_COLUMNS):
                raise RuntimeError(
                    "Unversioned database is not the supported baseline; migrate manually"
                )
            for table, columns in LEGACY_COLUMNS.items():
                actual = {c["name"]: c for c in inspector.get_columns(table)}
                if set(actual) != set(columns):
                    raise RuntimeError("Unversioned database has incompatible columns")
                for name, expected in columns.items():
                    column = actual[name]
                    if (
                        column["type"].python_type.__name__ != expected["family"]
                        or column["nullable"] != expected["nullable"]
                        or getattr(column["type"], "length", None) != expected["length"]
                    ):
                        raise RuntimeError(
                            "Unversioned database has incompatible column definitions"
                        )
            command.stamp(config_for(connection), "0001_baseline")
        command.upgrade(config_for(connection), revision)
        return MigrationContext.configure(connection).get_current_revision()
