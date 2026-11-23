import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(os.getenv("DOCINTEL_DATA", "data")).resolve()
SCHEMA = Path(__file__).with_name("schema.sql")


@contextmanager
def session(write=False):
    connection = sqlite3.connect(ROOT / "documents.sqlite3", timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        if write:
            connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize():
    (ROOT / "uploads").mkdir(parents=True, exist_ok=True)
    with session() as db:
        if db.execute("PRAGMA user_version").fetchone()[0] > 2:
            raise RuntimeError("The database schema is newer than this application.")
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA.read_text(encoding="utf-8") + "\nCOMMIT;")
