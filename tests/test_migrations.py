from alembic import command
from alembic.migration import MigrationContext
from emotional_robot.db import make_database
from emotional_robot.memory import add_memory
from emotional_robot.migrations.manager import config_for, migrate
from emotional_robot.models import Memory
from emotional_robot.security import issue_user
from sqlalchemy import inspect, select, text


def test_legacy_adoption_preserves_data(tmp_path):
    engine, factory = make_database(f"sqlite:///{tmp_path / 'old.db'}", initialize=False)
    migrate(engine, "0001_baseline")
    with factory.begin() as session:
        user, _ = issue_user(session, "旧用户")
        memory = add_memory(session, user.id, content="旧版本的记忆")
        mid = memory.id
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE alembic_version")
    assert migrate(engine) == "0002_vectors_receipts"
    assert migrate(engine) == "0002_vectors_receipts"
    with factory() as session:
        assert session.get(Memory, mid).content == "旧版本的记忆"
    assert "memory_embeddings" in inspect(engine).get_table_names()
    engine.dispose()


def test_unknown_unversioned_schema_is_not_stamped(tmp_path):
    import pytest

    engine, _ = make_database(f"sqlite:///{tmp_path / 'other.db'}", initialize=False)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO unrelated VALUES (42)"))
    with pytest.raises(RuntimeError, match="not the supported baseline"):
        migrate(engine)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT id FROM unrelated")) == 42
        assert "alembic_version" not in inspect(conn).get_table_names()
    engine.dispose()


def test_vector_migration_can_roll_back_without_losing_memories(tmp_path):
    engine, factory = make_database(f"sqlite:///{tmp_path / 'rollback.db'}")
    with factory.begin() as session:
        user, _ = issue_user(session, "用户")
        add_memory(session, user.id, content="不能丢失")
    with engine.begin() as conn:
        command.downgrade(config_for(conn), "0001_baseline")
        assert MigrationContext.configure(conn).get_current_revision() == "0001_baseline"
    with factory() as session:
        assert session.scalar(select(Memory.content)) == "不能丢失"
    migrate(engine)
    engine.dispose()
