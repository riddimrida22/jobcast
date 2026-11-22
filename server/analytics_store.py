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
    # timeout waits on a locked DB instead of raising; WAL lets readers and a writer
    # work concurrently; these matter under a traffic spike when many requests write at once.
    conn = sqlite3.connect(str(_db_path()), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error:
        pass
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
    # What people actually search: the job they checked, its score, and whether we could offer
    # a safer "green" move. Data-only (soc/title/score are public occupation facts, no PII), so
    # we can see demand and where the green payoff lands. Same store, same persistent disk.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            day TEXT NOT NULL,
            soc TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            score INTEGER,
            green TEXT NOT NULL DEFAULT ''
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_as_ts ON assessments(ts)")
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


def record_assessment(soc: str, title: str, score, green: str = "", ts: int = None) -> None:
    """Best-effort: log one job search. green is one of 'green' | 'soft' | 'low' | 'none' | ''
    (how the safer-move match resolved). Never raises."""
    try:
        now = int(ts if ts is not None else time.time())
        day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
        sc = int(round(score)) if isinstance(score, (int, float)) else None
        with _conn() as conn:
            conn.execute(
                "INSERT INTO assessments (ts, day, soc, title, score, green) VALUES (?,?,?,?,?,?)",
                (now, day, (soc or "")[:20], (title or "")[:120], sc, (green or "")[:8]),
            )
    except Exception as e:
        print(f"[analytics] record_assessment failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)


def top_jobs(days: int = 30, limit: int = 30) -> List[Dict[str, Any]]:
    """Most-searched jobs over the window, with how many searches, the average score, and how
    often a safer green move was found. Best-effort; returns [] if unavailable."""
    try:
        cutoff = int(time.time()) - days * 86400
        with _conn() as conn:
            rows = conn.execute(
                "SELECT soc, title, COUNT(*) n, "
                "       CAST(ROUND(AVG(score)) AS INT) avg_score, "
                "       SUM(CASE WHEN green IN ('green','soft') THEN 1 ELSE 0 END) green_n "
                "FROM assessments WHERE ts>=? AND title<>'' "
                "GROUP BY soc, title ORDER BY n DESC, avg_score DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
        return [{"soc": r["soc"], "title": r["title"], "n": r["n"],
                 "avg_score": r["avg_score"], "green_n": r["green_n"] or 0} for r in rows]
    except Exception as e:
        print(f"[analytics] top_jobs failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return []


def assessment_totals(days: int = 30) -> Dict[str, int]:
    """Window totals for the search log: how many searches, distinct jobs, and the share that
    got a green move. Best-effort."""
    try:
        cutoff = int(time.time()) - days * 86400
        with _conn() as conn:
            r = conn.execute(
                "SELECT COUNT(*) n, COUNT(DISTINCT soc) jobs, "
                "SUM(CASE WHEN green IN ('green','soft') THEN 1 ELSE 0 END) green_n "
                "FROM assessments WHERE ts>=?", (cutoff,)).fetchone()
        return {"searches": r["n"] or 0, "jobs": r["jobs"] or 0, "green_n": r["green_n"] or 0}
    except Exception:
        return {"searches": 0, "jobs": 0, "green_n": 0}


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
