"""First-party, privacy-preserving page-view analytics.

No third-party tracker, no cookies, no personal data stored. Each view records the
path, the day, the external referrer host, and a per-day visitor hash (a salted hash
of IP + user-agent + date, so the same person counts once per day and the raw IP is
never kept). Lives in its own SQLite file next to the watch store, on the same
persistent disk (JOBCAST_DATA_DIR) so it survives redeploys.

Recording is best-effort: any failure is swallowed so analytics can never break a
page render."""

import os
import sys
import time
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

_REPO_DATA = Path(__file__).resolve().parents[1] / "data"


def _db_path() -> Path:
    from .datadir import data_dir
    return data_dir() / "analytics.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pageviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            day TEXT NOT NULL,
            path TEXT NOT NULL,
            ref TEXT NOT NULL DEFAULT '',
            vid TEXT NOT NULL DEFAULT ''
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_pv_ts ON pageviews(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_pv_day ON pageviews(day)")
    return conn


def record(path: str, ref: str = "", vid: str = "", ts: int = None) -> None:
    """Best-effort: store one page view. Never raises."""
    try:
        now = int(ts if ts is not None else time.time())
        day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
        with _conn() as conn:
            conn.execute(
                "INSERT INTO pageviews (ts, day, path, ref, vid) VALUES (?,?,?,?,?)",
                (now, day, (path or "")[:200], (ref or "")[:120], (vid or "")[:64]),
            )
    except Exception as e:  # analytics must never break a request
        print(f"[analytics] record failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)


def _window(conn, cutoff: int) -> Dict[str, int]:
    row = conn.execute(
        "SELECT COUNT(*) v, COUNT(DISTINCT vid) u FROM pageviews WHERE ts>=?",
        (cutoff,),
    ).fetchone()
    return {"views": row["v"] or 0, "visitors": row["u"] or 0}


def summary(days: int = 30) -> Dict[str, Any]:
    """Totals, a per-day series, top pages and top referrers over the window.
    Best-effort: returns zeros if the store is unavailable."""
    try:
        now = int(time.time())
        cutoff = now - days * 86400
        cutoff7 = now - 7 * 86400
        cutoff1 = now - 86400
        with _conn() as conn:
            win = _window(conn, cutoff)
            win7 = _window(conn, cutoff7)
            win1 = _window(conn, cutoff1)
            all_time = _window(conn, 0)
            by_day: List[Dict[str, Any]] = [
                {"day": r["day"], "views": r["v"], "visitors": r["u"]}
                for r in conn.execute(
                    "SELECT day, COUNT(*) v, COUNT(DISTINCT vid) u FROM pageviews "
                    "WHERE ts>=? GROUP BY day ORDER BY day DESC",
                    (cutoff,),
                ).fetchall()
            ]
            top_paths = [
                {"path": r["path"], "views": r["v"], "visitors": r["u"]}
                for r in conn.execute(
                    "SELECT path, COUNT(*) v, COUNT(DISTINCT vid) u FROM pageviews "
                    "WHERE ts>=? GROUP BY path ORDER BY v DESC LIMIT 20",
                    (cutoff,),
                ).fetchall()
            ]
            top_refs = [
                {"ref": r["ref"], "views": r["v"]}
                for r in conn.execute(
                    "SELECT ref, COUNT(*) v FROM pageviews "
                    "WHERE ts>=? AND ref<>'' GROUP BY ref ORDER BY v DESC LIMIT 20",
                    (cutoff,),
                ).fetchall()
            ]
        return {
            "days": days,
            "today": win1, "last7": win7, "window": win, "all_time": all_time,
            "by_day": by_day, "top_paths": top_paths, "top_refs": top_refs,
        }
    except Exception as e:
        print(f"[analytics] summary failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        z = {"views": 0, "visitors": 0}
        return {"days": days, "today": z, "last7": z, "window": z, "all_time": z,
                "by_day": [], "top_paths": [], "top_refs": []}
