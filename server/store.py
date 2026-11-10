"""Durable store for outlook watches (who asked to be told when a job's automation
outlook shifts) and the last-known outlook we compared against.

SQLite so it survives restarts, unlike the old append-only signup file. The database
path comes from JOBCAST_DATA_DIR (set it to a mounted persistent disk in production);
locally it defaults to the repo's data/ folder. With no disk mounted on the host the
file still works, it just resets on redeploy - same failure mode as before, but the
production path is a one-line env + disk away."""

import os
import time
import json
import sqlite3
import secrets
from pathlib import Path
from typing import Optional, List, Dict, Any

_REPO_DATA = Path(__file__).resolve().parents[1] / "data"


def _db_path() -> Path:
    from .datadir import data_dir
    return data_dir() / "watches.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS watches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            soc TEXT,
            source TEXT,
            created_ts INTEGER,
            last_exposure REAL,
            last_demand REAL,
            last_notified_ts INTEGER,
            active INTEGER NOT NULL DEFAULT 1,
            token TEXT
        )"""
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_watch_email_soc ON watches(email, soc)"
    )
    return conn


def add_watch(email: str, soc: Optional[str] = None, source: str = "",
              exposure: Optional[float] = None, demand: Optional[float] = None) -> str:
    """Record (or revive) a watch for this email + job. Returns the unsubscribe token.

    The baseline outlook (exposure/demand) is stored only when first seen, so an existing
    watch keeps comparing against the value it was last notified at."""
    email = (email or "").strip().lower()
    soc = (soc or None)
    now = int(time.time())
    token = secrets.token_urlsafe(16)
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, token FROM watches WHERE email=? AND IFNULL(soc,'')=IFNULL(?, '')",
            (email, soc),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE watches SET active=1, source=COALESCE(NULLIF(?,''), source) WHERE id=?",
                (source, row["id"]),
            )
            # Only set a baseline if we never had one (do not reset an armed watch).
            conn.execute(
                "UPDATE watches SET last_exposure=COALESCE(last_exposure, ?), "
                "last_demand=COALESCE(last_demand, ?) WHERE id=?",
                (exposure, demand, row["id"]),
            )
            return row["token"]
        conn.execute(
            "INSERT INTO watches (email, soc, source, created_ts, last_exposure, last_demand, "
            "last_notified_ts, active, token) VALUES (?,?,?,?,?,?,?,1,?)",
            (email, soc, source, now, exposure, demand, None, token),
        )
    return token


def active_watches(with_soc: bool = True) -> List[Dict[str, Any]]:
    q = "SELECT * FROM watches WHERE active=1"
    if with_soc:
        q += " AND soc IS NOT NULL AND soc <> ''"
    with _conn() as conn:
        return [dict(r) for r in conn.execute(q).fetchall()]


def set_state(watch_id: int, exposure: Optional[float], demand: Optional[float],
              notified_ts: Optional[int] = None) -> None:
    with _conn() as conn:
        if notified_ts is None:
            conn.execute("UPDATE watches SET last_exposure=?, last_demand=? WHERE id=?",
                         (exposure, demand, watch_id))
        else:
            conn.execute(
                "UPDATE watches SET last_exposure=?, last_demand=?, last_notified_ts=? WHERE id=?",
                (exposure, demand, notified_ts, watch_id))


def deactivate(token: str) -> bool:
    token = (token or "").strip()
    if not token:
        return False
    with _conn() as conn:
        cur = conn.execute("UPDATE watches SET active=0 WHERE token=?", (token,))
        return cur.rowcount > 0


def counts() -> Dict[str, int]:
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM watches WHERE active=1").fetchone()["c"]
        armed = conn.execute(
            "SELECT COUNT(*) c FROM watches WHERE active=1 AND soc IS NOT NULL AND soc <> ''"
        ).fetchone()["c"]
    return {"active": total, "job_watches": armed}
