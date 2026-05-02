import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path("data/app.db")
REFS_DIR = Path("data/refs")
DOCS_DIR = Path("data/docs")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reference_files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    stored_path  TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    original_filename TEXT NOT NULL,
    stored_path       TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'queued',
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    sections_json  TEXT NOT NULL,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    edited_count   INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    REFS_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript(_SCHEMA)


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
    stored_path: str
    created_at: str


@dataclass
class DocumentRow:
    id: int
    project_id: int
    original_filename: str
    stored_path: str
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
        cur = conn.execute(
            "INSERT INTO projects (name, description, created_at) VALUES (?, ?, ?)",
            (name, description, _now()),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_projects() -> list[ProjectRow]:
    with _conn() as conn:
        rows = conn.execute("""
            SELECT p.id, p.name, p.description, p.created_at,
                   COUNT(d.id) AS document_count,
                   SUM(CASE WHEN d.status = 'complete' THEN 1 ELSE 0 END) AS completed_count
            FROM projects p
            LEFT JOIN documents d ON d.project_id = p.id
            GROUP BY p.id
            ORDER BY p.created_at DESC
        """).fetchall()
        return [ProjectRow(
            id=r["id"], name=r["name"], description=r["description"],
            created_at=r["created_at"],
            document_count=r["document_count"] or 0,
            completed_count=r["completed_count"] or 0,
        ) for r in rows]


def get_project(project_id: int) -> Optional[ProjectRow]:
    with _conn() as conn:
        r = conn.execute(
            "SELECT id, name, description, created_at FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        return None if not r else ProjectRow(
            id=r["id"], name=r["name"], description=r["description"], created_at=r["created_at"],
        )


def delete_project(project_id: int) -> None:
    for d in [REFS_DIR / str(project_id), DOCS_DIR / str(project_id)]:
        if d.exists():
            shutil.rmtree(d)
    with _conn() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


# ── Reference files ───────────────────────────────────────────────────────────

def add_reference_file(project_id: int, filename: str, file_bytes: bytes) -> int:
    proj_refs_dir = REFS_DIR / str(project_id)
    proj_refs_dir.mkdir(parents=True, exist_ok=True)
    stored_path = proj_refs_dir / f"{_ts()}_{filename}"
    stored_path.write_bytes(file_bytes)
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO reference_files (project_id, filename, stored_path, created_at) VALUES (?, ?, ?, ?)",
            (project_id, filename, str(stored_path), _now()),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_reference_files(project_id: int) -> list[RefFileRow]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, project_id, filename, stored_path, created_at "
            "FROM reference_files WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [RefFileRow(
            id=r["id"], project_id=r["project_id"], filename=r["filename"],
            stored_path=r["stored_path"], created_at=r["created_at"],
        ) for r in rows]


def delete_reference_file(ref_id: int) -> None:
    with _conn() as conn:
        row = conn.execute("SELECT stored_path FROM reference_files WHERE id = ?", (ref_id,)).fetchone()
        if row:
            Path(row["stored_path"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM reference_files WHERE id = ?", (ref_id,))


# ── Documents ─────────────────────────────────────────────────────────────────

def add_document(project_id: int, filename: str, file_bytes: bytes) -> int:
    proj_docs_dir = DOCS_DIR / str(project_id)
    proj_docs_dir.mkdir(parents=True, exist_ok=True)
    stored_path = proj_docs_dir / f"{_ts()}_{filename}"
    stored_path.write_bytes(file_bytes)
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO documents (project_id, original_filename, stored_path, status, created_at) "
            "VALUES (?, ?, ?, 'queued', ?)",
            (project_id, filename, str(stored_path), _now()),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_documents(project_id: int) -> list[DocumentRow]:
    with _conn() as conn:
        rows = conn.execute("""
            SELECT d.id, d.project_id, d.original_filename, d.stored_path, d.status, d.created_at,
                   COUNT(s.id) AS session_count
            FROM documents d
            LEFT JOIN sessions s ON s.document_id = d.id
            WHERE d.project_id = ?
            GROUP BY d.id
            ORDER BY d.created_at DESC
        """, (project_id,)).fetchall()
        return [DocumentRow(
            id=r["id"], project_id=r["project_id"], original_filename=r["original_filename"],
            stored_path=r["stored_path"], status=r["status"], created_at=r["created_at"],
            session_count=r["session_count"] or 0,
        ) for r in rows]


def get_document(doc_id: int) -> Optional[DocumentRow]:
    with _conn() as conn:
        r = conn.execute(
            "SELECT id, project_id, original_filename, stored_path, status, created_at "
            "FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        return None if not r else DocumentRow(
            id=r["id"], project_id=r["project_id"], original_filename=r["original_filename"],
            stored_path=r["stored_path"], status=r["status"], created_at=r["created_at"],
        )


def update_document_status(doc_id: int, status: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE documents SET status = ? WHERE id = ?", (status, doc_id))


def delete_document(doc_id: int) -> None:
    with _conn() as conn:
        row = conn.execute("SELECT stored_path FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if row:
            Path(row["stored_path"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


# ── Sessions ──────────────────────────────────────────────────────────────────

def save_session(
    document_id: int,
    sections_json: str,
    accepted_count: int,
    rejected_count: int,
    edited_count: int,
) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO sessions "
            "(document_id, sections_json, accepted_count, rejected_count, edited_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (document_id, sections_json, accepted_count, rejected_count, edited_count, _now()),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_sessions(document_id: int) -> list[SessionRow]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, document_id, sections_json, accepted_count, rejected_count, edited_count, created_at "
            "FROM sessions WHERE document_id = ? ORDER BY created_at DESC",
            (document_id,),
        ).fetchall()
        return [SessionRow(
            id=r["id"], document_id=r["document_id"], sections_json=r["sections_json"],
            accepted_count=r["accepted_count"], rejected_count=r["rejected_count"],
            edited_count=r["edited_count"], created_at=r["created_at"],
        ) for r in rows]


def get_session(session_id: int) -> Optional[SessionRow]:
    with _conn() as conn:
        r = conn.execute(
            "SELECT id, document_id, sections_json, accepted_count, rejected_count, edited_count, created_at "
            "FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return None if not r else SessionRow(
            id=r["id"], document_id=r["document_id"], sections_json=r["sections_json"],
            accepted_count=r["accepted_count"], rejected_count=r["rejected_count"],
            edited_count=r["edited_count"], created_at=r["created_at"],
        )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")
