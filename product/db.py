"""Postgres access: a small connection helper and the migration runner. SQL is written out in full (product/service.py);
there is no ORM to hide what a query reads or writes."""
import contextlib
import os
import threading

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import config

MIGRATIONS = os.path.join(os.path.dirname(__file__), "migrations")
_local = threading.local()


def connect(url=None):
    return psycopg.connect(url or config.DATABASE_URL, row_factory=dict_row, autocommit=False)


@contextlib.contextmanager
def session(url=None):
    """One connection and one transaction: committed when the block ends, rolled back if it raises."""
    conn = connect(url)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate(url=None):
    """Apply every migration not yet applied, in order. Each runs in its own transaction."""
    applied = []
    with connect(url) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        conn.commit()
        have = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
        for name in sorted(f for f in os.listdir(MIGRATIONS) if f.endswith(".sql")):
            version = name.split("_", 1)[0]
            if version in have:
                continue
            with open(os.path.join(MIGRATIONS, name), encoding="utf-8") as f:
                sql = f.read()
            with conn.transaction():
                conn.execute(sql)
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            applied.append(name)
    return applied


def pending_migrations(url=None):
    """Migrations on disk that this database hasn't applied: the code is ahead of the schema."""
    with connect(url) as conn:
        if conn.execute("SELECT to_regclass('public.schema_migrations') AS t").fetchone()["t"] is None:
            have = set()
        else:
            have = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
    return [f for f in sorted(os.listdir(MIGRATIONS)) if f.endswith(".sql") and f.split("_", 1)[0] not in have]


def one(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()


def all_(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def jsonb(value):
    return Jsonb(value)
