import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None

_TABLES = [
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


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError(
                "DATABASE_URL is not set. "
                "Add it to your Streamlit secrets or .env file."
            )
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 5, url)
    return _pool


@contextmanager
def _conn():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def init_db() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            for stmt in _TABLES:
                cur.execute(stmt)


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
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO projects (name, description, created_at) VALUES (%s, %s, %s) RETURNING id",
                (name, description, _now()),
            )
            return cur.fetchone()[0]


def get_projects() -> list[ProjectRow]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
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
            ) for r in cur.fetchall()]


def get_project(project_id: int) -> Optional[ProjectRow]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name, description, created_at FROM projects WHERE id = %s",
                (project_id,),
            )
            r = cur.fetchone()
            return None if not r else ProjectRow(
                id=r["id"], name=r["name"], description=r["description"], created_at=r["created_at"],
            )


def delete_project(project_id: int) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))


# ── Reference files ───────────────────────────────────────────────────────────

def add_reference_file(project_id: int, filename: str, file_bytes: bytes) -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO reference_files (project_id, filename, file_bytes, created_at) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (project_id, filename, psycopg2.Binary(file_bytes), _now()),
            )
            return cur.fetchone()[0]


def get_reference_files(project_id: int) -> list[RefFileRow]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, project_id, filename, file_bytes, created_at "
                "FROM reference_files WHERE project_id = %s ORDER BY created_at",
                (project_id,),
            )
            return [RefFileRow(
                id=r["id"], project_id=r["project_id"], filename=r["filename"],
                file_bytes=bytes(r["file_bytes"]),
                created_at=r["created_at"],
            ) for r in cur.fetchall()]


def delete_reference_file(ref_id: int) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM reference_files WHERE id = %s", (ref_id,))


# ── Documents ─────────────────────────────────────────────────────────────────

def add_document(project_id: int, filename: str, file_bytes: bytes) -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO documents (project_id, original_filename, file_bytes, status, created_at) "
                "VALUES (%s, %s, %s, 'queued', %s) RETURNING id",
                (project_id, filename, psycopg2.Binary(file_bytes), _now()),
            )
            return cur.fetchone()[0]


def get_documents(project_id: int) -> list[DocumentRow]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
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
                file_bytes=bytes(r["file_bytes"]),
                status=r["status"], created_at=r["created_at"],
                session_count=r["session_count"] or 0,
            ) for r in cur.fetchall()]


def get_document(doc_id: int) -> Optional[DocumentRow]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, project_id, original_filename, file_bytes, status, created_at "
                "FROM documents WHERE id = %s",
                (doc_id,),
            )
            r = cur.fetchone()
            return None if not r else DocumentRow(
                id=r["id"], project_id=r["project_id"],
                original_filename=r["original_filename"],
                file_bytes=bytes(r["file_bytes"]),
                status=r["status"], created_at=r["created_at"],
            )


def update_document_status(doc_id: int, status: str) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE documents SET status = %s WHERE id = %s", (status, doc_id))


def delete_document(doc_id: int) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (doc_id,))


# ── Sessions ──────────────────────────────────────────────────────────────────

def save_session(
    document_id: int,
    sections_json: str,
    accepted_count: int,
    rejected_count: int,
    edited_count: int,
) -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sessions "
                "(document_id, sections_json, accepted_count, rejected_count, edited_count, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (document_id, sections_json, accepted_count, rejected_count, edited_count, _now()),
            )
            return cur.fetchone()[0]


def get_sessions(document_id: int) -> list[SessionRow]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, document_id, sections_json, accepted_count, rejected_count, "
                "edited_count, created_at "
                "FROM sessions WHERE document_id = %s ORDER BY created_at DESC",
                (document_id,),
            )
            return [SessionRow(
                id=r["id"], document_id=r["document_id"], sections_json=r["sections_json"],
                accepted_count=r["accepted_count"], rejected_count=r["rejected_count"],
                edited_count=r["edited_count"], created_at=r["created_at"],
            ) for r in cur.fetchall()]


def get_session(session_id: int) -> Optional[SessionRow]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, document_id, sections_json, accepted_count, rejected_count, "
                "edited_count, created_at "
                "FROM sessions WHERE id = %s",
                (session_id,),
            )
            r = cur.fetchone()
            return None if not r else SessionRow(
                id=r["id"], document_id=r["document_id"], sections_json=r["sections_json"],
                accepted_count=r["accepted_count"], rejected_count=r["rejected_count"],
                edited_count=r["edited_count"], created_at=r["created_at"],
            )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
