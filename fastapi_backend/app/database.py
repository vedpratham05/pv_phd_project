from __future__ import annotations

import os
import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


# 1. ORM BASE CLASS
class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


# 2. PATH DEFINITIONS
# Resolved relative to this file so the project works on any machine
# (no hardcoded /Users/... paths). Because different layouts keep the
# .db files in different places (next to this file, at the package root,
# or at the project root), we SEARCH upward for an existing file first —
# this prevents accidentally creating a fresh empty database and losing
# access to existing data. Only if no existing file is found anywhere do
# we create a new one at the project root.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def _table_count(db_path: str) -> int:
    """Number of user tables inside a SQLite file (0 for empty/corrupt)."""
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()
    except Exception:
        return 0


def _locate_db(filename: str) -> str:
    """Find the REAL db file by walking up from this file's directory
    (covers layouts like fastapi_backend/, fastapi_backend/app/,
    fastapi_backend/app/api/, and the project root).

    IMPORTANT: earlier path bugs may have left stale EMPTY .db files next
    to the code. A candidate only counts if it actually contains tables —
    among all candidates with data, the one with the most tables wins.
    Falls back to the project root for genuinely fresh installs."""
    search_dirs = []
    current = _THIS_DIR
    for _ in range(4):  # this dir + up to 3 parents
        search_dirs.append(current)
        current = os.path.dirname(current)

    best_path = None
    best_tables = 0
    for directory in search_dirs:
        candidate = os.path.join(directory, filename)
        if os.path.exists(candidate):
            tables = _table_count(candidate)
            if tables > best_tables:
                best_path = candidate
                best_tables = tables

    if best_path:
        print(f"[*] Using existing database ({best_tables} tables): {best_path}")
        return best_path

    fallback = os.path.join(search_dirs[-1], filename)
    print(f"[*] No populated {filename} found — creating fresh at: {fallback}")
    return fallback


VISITOR_DB_PATH = _locate_db("visitor_system.db")
COLLEGE_DB_PATH = _locate_db("college_system.db")

# 3. ENGINES
# Visitor Engine (visitor_system.db): visitor registrations, visitor
# Aadhaar records, visitor face embeddings, QR passes, visit sessions,
# security alerts, and visitor verification logs.
visitor_engine = create_engine(
    f"sqlite:///{VISITOR_DB_PATH}",
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)

# College Engine (college_system.db): faculty/department records,
# faculty registrations, AND all faculty identity data — faculty
# aadhaar_master, faculty verification_logs, and faculty_face_embeddings.
# Faculty Aadhaar + face data must NEVER be written through the visitor
# engine; the two identity stores are fully separated.
college_engine = create_engine(
    f"sqlite:///{COLLEGE_DB_PATH}",
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)

# 4. SESSION FACTORIES
VisitorSessionLocal = sessionmaker(
    bind=visitor_engine,
    autocommit=False,
    autoflush=False,
)

SessionLocalCollege = sessionmaker(
    bind=college_engine,
    autocommit=False,
    autoflush=False,
)


# 5. DEPENDENCY INJECTION HOOKS
def get_visitor_db():
    """Provides an isolated session for visitor_system.db (visitor data only)."""
    db = VisitorSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_college_db():
    """Provides an isolated session for college_system.db (faculty data,
    including faculty Aadhaar records, verification logs, and face
    embeddings)."""
    db = SessionLocalCollege()
    try:
        yield db
    finally:
        db.close()
