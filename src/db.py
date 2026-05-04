"""
Database layer — works with either SQLite (default) or PostgreSQL.

SQLite is used automatically when DATABASE_URL is not set (local dev,
Streamlit Cloud without a secret). Set DATABASE_URL to a PostgreSQL
connection string to switch to persistent cloud storage.
"""

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_USE_POSTGRES = False  # set to True by init_db() when DATABASE_URL is present
_pg_pool: Any = None
_SQLITE_PATH = Path("data/app.db")

# ── Schema ────────────────────────────────────────────────────────────────────

# File bytes stored as BLOB (SQLite) or BYTEA (PostgreSQL) — no disk paths.
_TABLES_SQLITE = [
    """
    CREATE TABLE IF NOT EXISTS projects (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reference_files (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        filename     TEXT NOT NULL,
        file_bytes   BLOB NOT NULL,
        created_at   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS documents (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        original_filename TEXT NOT NULL,
        file_bytes        BLOB NOT NULL,
        status            TEXT NOT NULL DEFAULT 'queued',
        created_at        TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        sections_json  TEXT NOT NULL,
        accepted_count INTEGER NOT NULL DEFAULT 0,
        rejected_count INTEGER NOT NULL DEFAULT 0,
        edited_count   INTEGER NOT NULL DEFAULT 0,
        created_at     TEXT NOT NULL
    )
    """,
]

_TABLES_POSTGRES = [
    """
    CREATE TABLE IF NOT EXISTS projects (
        id          SERIAL PRIMARY KEY,
        name        TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reference_files (
        id           SERIAL PRIMARY KEY,
        project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        filename     TEXT NOT NULL,
        file_bytes   BYTEA NOT NULL,
        created_at   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS documents (
        id                SERIAL PRIMARY KEY,
        project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        original_filename TEXT NOT NULL,
        file_bytes        BYTEA NOT NULL,
        status            TEXT NOT NULL DEFAULT 'queued',
        created_at        TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id             SERIAL PRIMARY KEY,
        document_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        sections_json  TEXT NOT NULL,
        accepted_count INTEGER NOT NULL DEFAULT 0,
        rejected_count INTEGER NOT NULL DEFAULT 0,
        edited_count   INTEGER NOT NULL DEFAULT 0,
        created_at     TEXT NOT NULL
    )
    """,
]


# ── Connection management ─────────────────────────────────────────────────────

@contextmanager
def _conn():
    if _USE_POSTGRES:
        import psycopg2.pool as _pool_mod
        conn = _pg_pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _pg_pool.putconn(conn)
    else:
        _SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_SQLITE_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# ── SQL execution helpers ─────────────────────────────────────────────────────

def _q(sql: str) -> str:
    """Translate %s placeholders to ? for SQLite."""
    return sql if _USE_POSTGRES else sql.replace("%s", "?")


def _to_bytes(v: Any) -> bytes:
    return bytes(v) if isinstance(v, memoryview) else v


def _norm(row: Any) -> dict:
    """Convert a DB row to a plain dict, normalising BYTEA memoryviews to bytes."""
    d = dict(row)
    return {k: _to_bytes(v) for k, v in d.items()}


def _insert(conn, sql: str, params: tuple) -> int:
    """Execute an INSERT and return the new row id."""
    if _USE_POSTGRES:
        import psycopg2
        wrapped = tuple(psycopg2.Binary(p) if isinstance(p, bytes) else p for p in params)
        with conn.cursor() as cur:
            cur.execute(sql, wrapped)
            return cur.fetchone()[0]
    else:
        safe_sql = _q(sql.replace(" RETURNING id", ""))
        cur = conn.execute(safe_sql, params)
        return cur.lastrowid


def _fetchall(conn, sql: str, params: tuple = ()) -> list[dict]:
    if _USE_POSTGRES:
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [_norm(r) for r in cur.fetchall()]
    else:
        return [_norm(r) for r in conn.execute(_q(sql), params).fetchall()]


def _fetchone(conn, sql: str, params: tuple = ()) -> Optional[dict]:
    if _USE_POSTGRES:
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            r = cur.fetchone()
            return _norm(r) if r else None
    else:
        r = conn.execute(_q(sql), params).fetchone()
        return _norm(r) if r else None


def _execute(conn, sql: str, params: tuple = ()) -> None:
    if _USE_POSTGRES:
        with conn.cursor() as cur:
            cur.execute(sql, params)
    else:
        conn.execute(_q(sql), params)


# ── Init ──────────────────────────────────────────────────────────────────────

def init_db() -> None:
    global _USE_POSTGRES, _pg_pool
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if db_url:
        import psycopg2.pool as _pool_mod
        _USE_POSTGRES = True
        if _pg_pool is None:
            _pg_pool = _pool_mod.ThreadedConnectionPool(1, 5, db_url)
        tables = _TABLES_POSTGRES
    else:
        tables = _TABLES_SQLITE

    with _conn() as conn:
        for stmt in tables:
            _execute(conn, stmt)


# ── Row types ──────────────────────────────────────────────────────────────────

@dataclass
class ProjectRow:
    id: int
    name: str
    description: str
    created_at: str
    document_count: int = 0
    completed_count: int = 0


@dataclass
class RefFileRow:
    id: int
    project_id: int
    filename: str
    file_bytes: bytes
    created_at: str


@dataclass
class DocumentRow:
    id: int
    project_id: int
    original_filename: str
    file_bytes: bytes
    status: str
    created_at: str
    session_count: int = 0


@dataclass
class SessionRow:
    id: int
    document_id: int
    sections_json: str
    accepted_count: int
    rejected_count: int
    edited_count: int
    created_at: str


# ── Projects ──────────────────────────────────────────────────────────────────

def create_project(name: str, description: str) -> int:
    with _conn() as conn:
        return _insert(conn,
            "INSERT INTO projects (name, description, created_at) VALUES (%s, %s, %s) RETURNING id",
            (name, description, _now()),
        )


def get_projects() -> list[ProjectRow]:
    with _conn() as conn:
        rows = _fetchall(conn, """
            SELECT p.id, p.name, p.description, p.created_at,
                   COUNT(d.id) AS document_count,
                   SUM(CASE WHEN d.status = 'complete' THEN 1 ELSE 0 END) AS completed_count
            FROM projects p
            LEFT JOIN documents d ON d.project_id = p.id
            GROUP BY p.id
            ORDER BY p.created_at DESC
        """)
        return [ProjectRow(
            id=r["id"], name=r["name"], description=r["description"],
            created_at=r["created_at"],
            document_count=r["document_count"] or 0,
            completed_count=r["completed_count"] or 0,
        ) for r in rows]


def get_project(project_id: int) -> Optional[ProjectRow]:
    with _conn() as conn:
        r = _fetchone(conn,
            "SELECT id, name, description, created_at FROM projects WHERE id = %s",
            (project_id,),
        )
        return None if not r else ProjectRow(
            id=r["id"], name=r["name"], description=r["description"], created_at=r["created_at"],
        )


def delete_project(project_id: int) -> None:
    with _conn() as conn:
        _execute(conn, "DELETE FROM projects WHERE id = %s", (project_id,))


# ── Reference files ───────────────────────────────────────────────────────────

def add_reference_file(project_id: int, filename: str, file_bytes: bytes) -> int:
    with _conn() as conn:
        return _insert(conn,
            "INSERT INTO reference_files (project_id, filename, file_bytes, created_at) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (project_id, filename, file_bytes, _now()),
        )


def get_reference_files(project_id: int) -> list[RefFileRow]:
    with _conn() as conn:
        rows = _fetchall(conn,
            "SELECT id, project_id, filename, file_bytes, created_at "
            "FROM reference_files WHERE project_id = %s ORDER BY created_at",
            (project_id,),
        )
        return [RefFileRow(
            id=r["id"], project_id=r["project_id"], filename=r["filename"],
            file_bytes=r["file_bytes"], created_at=r["created_at"],
        ) for r in rows]


def delete_reference_file(ref_id: int) -> None:
    with _conn() as conn:
        _execute(conn, "DELETE FROM reference_files WHERE id = %s", (ref_id,))


# ── Documents ─────────────────────────────────────────────────────────────────

def add_document(project_id: int, filename: str, file_bytes: bytes) -> int:
    with _conn() as conn:
        return _insert(conn,
            "INSERT INTO documents (project_id, original_filename, file_bytes, status, created_at) "
            "VALUES (%s, %s, %s, 'queued', %s) RETURNING id",
            (project_id, filename, file_bytes, _now()),
        )


def get_documents(project_id: int) -> list[DocumentRow]:
    with _conn() as conn:
        rows = _fetchall(conn, """
            SELECT d.id, d.project_id, d.original_filename, d.file_bytes,
                   d.status, d.created_at,
                   COUNT(s.id) AS session_count
            FROM documents d
            LEFT JOIN sessions s ON s.document_id = d.id
            WHERE d.project_id = %s
            GROUP BY d.id
            ORDER BY d.created_at DESC
        """, (project_id,))
        return [DocumentRow(
            id=r["id"], project_id=r["project_id"],
            original_filename=r["original_filename"],
            file_bytes=r["file_bytes"],
            status=r["status"], created_at=r["created_at"],
            session_count=r["session_count"] or 0,
        ) for r in rows]


def get_document(doc_id: int) -> Optional[DocumentRow]:
    with _conn() as conn:
        r = _fetchone(conn,
            "SELECT id, project_id, original_filename, file_bytes, status, created_at "
            "FROM documents WHERE id = %s",
            (doc_id,),
        )
        return None if not r else DocumentRow(
            id=r["id"], project_id=r["project_id"],
            original_filename=r["original_filename"],
            file_bytes=r["file_bytes"],
            status=r["status"], created_at=r["created_at"],
        )


def update_document_status(doc_id: int, status: str) -> None:
    with _conn() as conn:
        _execute(conn, "UPDATE documents SET status = %s WHERE id = %s", (status, doc_id))


def delete_document(doc_id: int) -> None:
    with _conn() as conn:
        _execute(conn, "DELETE FROM documents WHERE id = %s", (doc_id,))


# ── Sessions ──────────────────────────────────────────────────────────────────

def save_session(
    document_id: int,
    sections_json: str,
    accepted_count: int,
    rejected_count: int,
    edited_count: int,
) -> int:
    with _conn() as conn:
        return _insert(conn,
            "INSERT INTO sessions "
            "(document_id, sections_json, accepted_count, rejected_count, edited_count, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (document_id, sections_json, accepted_count, rejected_count, edited_count, _now()),
        )


def get_sessions(document_id: int) -> list[SessionRow]:
    with _conn() as conn:
        rows = _fetchall(conn,
            "SELECT id, document_id, sections_json, accepted_count, rejected_count, "
            "edited_count, created_at "
            "FROM sessions WHERE document_id = %s ORDER BY created_at DESC",
            (document_id,),
        )
        return [SessionRow(
            id=r["id"], document_id=r["document_id"], sections_json=r["sections_json"],
            accepted_count=r["accepted_count"], rejected_count=r["rejected_count"],
            edited_count=r["edited_count"], created_at=r["created_at"],
        ) for r in rows]


def get_session(session_id: int) -> Optional[SessionRow]:
    with _conn() as conn:
        r = _fetchone(conn,
            "SELECT id, document_id, sections_json, accepted_count, rejected_count, "
            "edited_count, created_at "
            "FROM sessions WHERE id = %s",
            (session_id,),
        )
        return None if not r else SessionRow(
            id=r["id"], document_id=r["document_id"], sections_json=r["sections_json"],
            accepted_count=r["accepted_count"], rejected_count=r["rejected_count"],
            edited_count=r["edited_count"], created_at=r["created_at"],
        )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
