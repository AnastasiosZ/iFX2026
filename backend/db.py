"""
SQLite persistence for Finter.

Holds the data that must outlive a single request/process restart:

  - users           accounts (hashed+salted passwords), assigned persona,
                    and their latest personality vector.
  - personas        the trader archetypes (mirrored from personas.py so the
                    DB is self-contained and dummy users can reference them).
  - likes           which user liked which instrument (the social signal that
                    powers "traders like you invested in this").
  - recommendations a log of what we surfaced to each user and why.

Plus a set of DUMMY users — a few per persona, each pre-seeded with a basket of
liked instruments. These stand in for a real user base: at recommend time, 40%
of the collaborative score for a user comes from the instruments liked by *other
users who share the user's persona* (see recommender.py).

Stdlib sqlite3 only — zero extra dependencies, single-file DB, demo-safe. The
module keeps one shared connection guarded by a lock because both request
threads and the background data-refresh thread touch it.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from . import auth
from .personas import PERSONAS

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "finter.db"

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

# How many dummy users to create per persona. Each one likes that persona's
# basket, giving a realistic "people like you also liked…" popularity signal.
DUMMY_USERS_PER_PERSONA = 4


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL;")
    return _conn


# ---------------------------------------------------------------- schema
_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    email         TEXT,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    persona_id    TEXT,
    base_vector   TEXT,                 -- JSON: 10-dim trait vector
    is_dummy      INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS personas (
    id     TEXT PRIMARY KEY,
    name   TEXT NOT NULL,
    blurb  TEXT,
    traits TEXT,                        -- JSON
    basket TEXT                         -- JSON list of symbols
);

CREATE TABLE IF NOT EXISTS likes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    symbol     TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(user_id, symbol)
);

CREATE TABLE IF NOT EXISTS recommendations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    symbol     TEXT NOT NULL,
    score      REAL,
    reason     TEXT,
    strategy   TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_likes_user ON likes(user_id);
CREATE INDEX IF NOT EXISTS idx_likes_symbol ON likes(symbol);
CREATE INDEX IF NOT EXISTS idx_users_persona ON users(persona_id);
"""


def init_db() -> None:
    """Create tables (idempotent) and seed personas + dummy users on first run."""
    with _lock:
        conn = _connect()
        conn.executescript(_SCHEMA)
        conn.commit()
        _seed_personas()
        _seed_dummy_users()


# ---------------------------------------------------------------- seeding
def _seed_personas() -> None:
    conn = _connect()
    for p in PERSONAS:
        conn.execute(
            "INSERT OR REPLACE INTO personas(id, name, blurb, traits, basket) "
            "VALUES (?,?,?,?,?)",
            (p["id"], p["name"], p["blurb"], json.dumps(p["traits"]), json.dumps(p["basket"])),
        )
    conn.commit()


def _seed_dummy_users() -> None:
    """
    Create a handful of dummy users per persona, each liking that persona's
    basket (plus a couple of instruments borrowed from a neighbouring persona
    for variety). Deterministic and idempotent — skips if dummies already exist.
    """
    conn = _connect()
    existing = conn.execute("SELECT COUNT(*) AS n FROM users WHERE is_dummy=1").fetchone()["n"]
    if existing:
        return

    now = time.time()
    n_personas = len(PERSONAS)
    for pi, p in enumerate(PERSONAS):
        neighbour = PERSONAS[(pi + 1) % n_personas]  # for a little cross-pollination
        for k in range(DUMMY_USERS_PER_PERSONA):
            username = f"_dummy_{p['id']}_{k}"
            salt, pwd_hash = auth.hash_password(f"seed-{username}")
            cur = conn.execute(
                "INSERT INTO users(username, email, password_hash, salt, persona_id, "
                "base_vector, is_dummy, created_at) VALUES (?,?,?,?,?,?,1,?)",
                (username, f"{username}@finter.local", pwd_hash, salt, p["id"],
                 json.dumps(p["traits"]), now),
            )
            uid = cur.lastrowid
            # Like the whole persona basket, plus 2 instruments from the neighbour
            # so the same-persona signal isn't a perfect echo of the basket.
            symbols = list(p["basket"]) + neighbour["basket"][: 2 + (k % 2)]
            for sym in symbols:
                conn.execute(
                    "INSERT OR IGNORE INTO likes(user_id, symbol, created_at) VALUES (?,?,?)",
                    (uid, sym, now),
                )
    conn.commit()


# ---------------------------------------------------------------- users
def create_user(username: str, email: str, password: str) -> dict:
    salt, pwd_hash = auth.hash_password(password)
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "INSERT INTO users(username, email, password_hash, salt, base_vector, "
            "is_dummy, created_at) VALUES (?,?,?,?,?,0,?)",
            (username, email, pwd_hash, salt, None, time.time()),
        )
        conn.commit()
        return get_user_by_id(cur.lastrowid)


def get_user_by_username(username: str) -> dict | None:
    with _lock:
        row = _connect().execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()
        return _row_to_user(row)


def get_user_by_id(user_id: int) -> dict | None:
    with _lock:
        row = _connect().execute(
            "SELECT * FROM users WHERE id=?", (user_id,)
        ).fetchone()
        return _row_to_user(row)


def update_user_profile(user_id: int, base_vector: dict, persona_id: str | None) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "UPDATE users SET base_vector=?, persona_id=? WHERE id=?",
            (json.dumps(base_vector), persona_id, user_id),
        )
        conn.commit()


def _row_to_user(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "password_hash": row["password_hash"],
        "salt": row["salt"],
        "persona_id": row["persona_id"],
        "base_vector": json.loads(row["base_vector"]) if row["base_vector"] else None,
        "is_dummy": bool(row["is_dummy"]),
    }


# ---------------------------------------------------------------- likes
def add_like(user_id: int, symbol: str) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT OR IGNORE INTO likes(user_id, symbol, created_at) VALUES (?,?,?)",
            (user_id, symbol, time.time()),
        )
        conn.commit()


def remove_like(user_id: int, symbol: str) -> None:
    with _lock:
        conn = _connect()
        conn.execute("DELETE FROM likes WHERE user_id=? AND symbol=?", (user_id, symbol))
        conn.commit()


def get_user_likes(user_id: int) -> list[str]:
    with _lock:
        rows = _connect().execute(
            "SELECT symbol FROM likes WHERE user_id=? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [r["symbol"] for r in rows]


def likes_by_persona(persona_id: str, exclude_user_id: int | None = None) -> dict[str, int]:
    """
    symbol -> number of users with this persona who liked it. This is the raw
    'people who match your trader DNA also liked…' signal.
    """
    if not persona_id:
        return {}
    sql = (
        "SELECT l.symbol AS symbol, COUNT(*) AS n "
        "FROM likes l JOIN users u ON u.id = l.user_id "
        "WHERE u.persona_id = ?"
    )
    params: list = [persona_id]
    if exclude_user_id is not None:
        sql += " AND u.id != ?"
        params.append(exclude_user_id)
    sql += " GROUP BY l.symbol"
    with _lock:
        rows = _connect().execute(sql, params).fetchall()
        return {r["symbol"]: r["n"] for r in rows}


# ---------------------------------------------------------------- recommendations log
def log_recommendations(user_id: int, items: list[dict]) -> None:
    """Persist the top recommendations shown to a user (best-effort, for history)."""
    now = time.time()
    with _lock:
        conn = _connect()
        conn.executemany(
            "INSERT INTO recommendations(user_id, symbol, score, reason, strategy, created_at) "
            "VALUES (?,?,?,?,?,?)",
            [
                (user_id, it["symbol"], it.get("match"), it.get("why"),
                 (it.get("strategy") or {}).get("text"), now)
                for it in items
            ],
        )
        conn.commit()
