"""SQLite snapshot/restore for a single-host deployment, with deletion-journal replay."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from sqlalchemy.engine import make_url

from .db import make_database
from .ledger import DeletionLedger, replay_deletions


def manifest_path(path):
    return Path(str(path) + ".manifest.json")


def copy_snapshot(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file() or source == destination:
        raise ValueError("Backup source must be an existing separate database")
    if destination.exists() or manifest_path(destination).exists():
        raise ValueError("Destination already exists; select a new file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as reader:
        if reader.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Source database integrity check failed")
        with destination.open("xb"):
            pass
        with closing(sqlite3.connect(destination)) as writer:
            reader.backup(writer)


def backup_sqlite(settings, output):
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise ValueError("This backup command supports file-based SQLite only")
    ledger = DeletionLedger(settings.deletion_ledger_path)
    identity = ledger.ensure()
    output = Path(output).resolve()
    if output == ledger.path.resolve():
        raise ValueError("Backup must not overwrite the deletion ledger")
    copy_snapshot(url.database, output)
    with manifest_path(output).open("x", encoding="utf-8") as file:
        json.dump(
            {"format_version": 1, "ledger_id": identity, "requires_deletion_ledger": True}, file
        )
    return {"backup": str(output), "ledger_id": identity}


def restore_sqlite(settings, backup, output):
    ledger = DeletionLedger(settings.deletion_ledger_path)
    with manifest_path(backup).open(encoding="utf-8") as file:
        manifest = json.load(file)
    if manifest.get("format_version") != 1 or manifest.get("ledger_id") != ledger.identity():
        raise ValueError("The matching original deletion ledger is required")
    output = Path(output).resolve()
    if output == ledger.path.resolve():
        raise ValueError("Restore must not overwrite the deletion ledger")
    copy_snapshot(backup, output)
    engine, factory = make_database("sqlite:///" + str(output))
    try:
        applied = replay_deletions(factory, ledger)
    finally:
        engine.dispose()
    return {"database": str(output), "replayed_deletions": applied}
