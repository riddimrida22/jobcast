"""Referral program.

A user (identified by email) gets a short referral code. Friends who arrive on their
link (?r=code) and then PAY are credited to that referrer. At THRESHOLD paid referrals the
referrer earns a one-time REWARD_PERCENT%-off code (issued from the Stripe webhook).

Only PAID conversions count - credited from checkout.session.completed - so the reward
cannot be farmed with free sign-ups. SQLite so counts survive restarts and stay correct
across gunicorn workers; the same Stripe session can never be counted twice (UNIQUE).
"""

import time
import secrets
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any

THRESHOLD = 5
REWARD_PERCENT = 50


def _db_path() -> Path:
    from .datadir import data_dir
    return data_dir() / "referrals.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS referrers (
            code TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            created_ts INTEGER,
            rewarded_ts INTEGER,
            reward_code TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_code TEXT NOT NULL,
            stripe_session TEXT UNIQUE,
            ts INTEGER
        )"""
    )
    return conn


def valid_code(code: str) -> bool:
    return bool(code) and len(code) <= 16 and str(code).isalnum()


def code_for_email(email: str) -> Optional[str]:
    """Get or create this email's referral code (one per email)."""
    email = (email or "").strip().lower()
    if not email or "@" not in email or len(email) > 254:
        return None
    with _conn() as conn:
        row = conn.execute("SELECT code FROM referrers WHERE email=?", (email,)).fetchone()
        if row:
            return row["code"]
        for _ in range(5):  # retry on the astronomically unlikely code collision
            code = secrets.token_hex(4)  # 8 hex chars
            try:
                conn.execute(
                    "INSERT INTO referrers (code, email, created_ts) VALUES (?,?,?)",
                    (code, email, int(time.time())),
                )
                return code
            except sqlite3.IntegrityError:
                continue
    return None


def email_for_code(code: str) -> Optional[str]:
    if not valid_code(code):
        return None
    with _conn() as conn:
        row = conn.execute("SELECT email FROM referrers WHERE code=?", (code,)).fetchone()
        return row["email"] if row else None


def credit(ref_code: str, stripe_session: str) -> int:
    """Credit one PAID referral to ref_code, keyed by the Stripe session id so the same
    checkout can never be counted twice. Returns the referrer's new paid-referral count
    (0 if the code is unknown)."""
    if not valid_code(ref_code):
        return 0
    with _conn() as conn:
        if not conn.execute("SELECT 1 FROM referrers WHERE code=?", (ref_code,)).fetchone():
            return 0
        try:
            conn.execute(
                "INSERT INTO referrals (ref_code, stripe_session, ts) VALUES (?,?,?)",
                (ref_code, stripe_session or ("nosess_" + secrets.token_hex(8)), int(time.time())),
            )
        except sqlite3.IntegrityError:
            pass  # this checkout session was already credited
        return conn.execute(
            "SELECT COUNT(*) AS n FROM referrals WHERE ref_code=?", (ref_code,)
        ).fetchone()["n"]


def count(ref_code: str) -> int:
    if not valid_code(ref_code):
        return 0
    with _conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM referrals WHERE ref_code=?", (ref_code,)
        ).fetchone()["n"]


def status(email: str) -> Dict[str, Any]:
    code = code_for_email(email)
    if not code:
        return {"code": None, "count": 0, "threshold": THRESHOLD,
                "rewarded": False, "reward_code": None}
    with _conn() as conn:
        row = conn.execute(
            "SELECT rewarded_ts, reward_code FROM referrers WHERE code=?", (code,)
        ).fetchone()
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM referrals WHERE ref_code=?", (code,)
        ).fetchone()["n"]
    return {"code": code, "count": n, "threshold": THRESHOLD,
            "rewarded": bool(row and row["rewarded_ts"]),
            "reward_code": row["reward_code"] if row else None}


def needs_reward(ref_code: str) -> bool:
    """True when this referrer has reached the threshold and has not been rewarded yet."""
    if not valid_code(ref_code):
        return False
    with _conn() as conn:
        row = conn.execute("SELECT rewarded_ts FROM referrers WHERE code=?", (ref_code,)).fetchone()
        if not row or row["rewarded_ts"]:
            return False
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM referrals WHERE ref_code=?", (ref_code,)
        ).fetchone()["n"]
        return n >= THRESHOLD


def mark_rewarded(ref_code: str, reward_code: str) -> bool:
    """Record the reward once. Returns True only if THIS call set it (atomic guard against
    issuing two rewards for the same referrer across concurrent workers)."""
    if not valid_code(ref_code):
        return False
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE referrers SET rewarded_ts=?, reward_code=? "
            "WHERE code=? AND rewarded_ts IS NULL",
            (int(time.time()), reward_code, ref_code),
        )
        return cur.rowcount > 0
