"""Free-for-students gate, built CLOSED so non-students can't use it to skip paying.

A verified **.edu** email unlocks the paid tier once per email: we email a 6-digit code to the
address (proving control -> you can't just type any .edu), and grant exactly one free unlock per
verified email (tied to the email, not a shareable cookie/code). Disposable / known-resale domains
are blocked outright. No payment path is touched."""

import re
import time
import secrets
import sqlite3
from pathlib import Path
from typing import Optional, Tuple

TIER = "tier2"
CODE_TTL = 1800          # a verification code is good for 30 minutes
_EDU_RE = re.compile(r"^[^@\s]+@[^@\s]+\.edu$")

# Known throwaway / disposable domains to refuse (extend as needed). A real enrollment check
# (SheerID/UNiDAYS) is the airtight upgrade; this closes the casual bypass.
_BLOCKED = {"mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
            "yopmail.com", "trashmail.com", "sharklasers.com"}


def _db_path() -> Path:
    from .datadir import data_dir
    return data_dir() / "students.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS students (
            email TEXT PRIMARY KEY,
            code TEXT,
            code_ts INTEGER,
            verified_ts INTEGER,
            granted INTEGER DEFAULT 0
        )"""
    )
    return conn


def eligible(email: str) -> Tuple[bool, str]:
    """(ok, reason). Must be a .edu address and not a blocked/disposable domain."""
    e = (email or "").strip().lower()
    if not _EDU_RE.match(e):
        return False, "need_edu"
    if e.split("@")[-1] in _BLOCKED:
        return False, "blocked_domain"
    return True, ""


def request_code(email: str) -> Optional[str]:
    """Generate + store a 6-digit code for an eligible .edu email, returning it for the caller to
    email. None if ineligible or this email already used its one free unlock."""
    e = (email or "").strip().lower()
    if not eligible(e)[0]:
        return None
    with _conn() as conn:
        row = conn.execute("SELECT granted FROM students WHERE email=?", (e,)).fetchone()
        if row and row["granted"]:
            return None                      # one free unlock per email, already used
        code = "%06d" % secrets.randbelow(1000000)
        conn.execute(
            "INSERT INTO students (email, code, code_ts) VALUES (?,?,?) "
            "ON CONFLICT(email) DO UPDATE SET code=excluded.code, code_ts=excluded.code_ts",
            (e, code, int(time.time())))
        return code


def verify(email: str, code: str) -> bool:
    """Check the code; on success mark the email granted (one-shot) and return True. The route
    then sets the entitlement. Expired, wrong, or already-granted codes return False."""
    e = (email or "").strip().lower()
    c = (code or "").strip()
    with _conn() as conn:
        row = conn.execute(
            "SELECT code, code_ts, granted FROM students WHERE email=?", (e,)).fetchone()
        if not row or row["granted"]:
            return False
        if not row["code"] or row["code"] != c:
            return False
        if int(time.time()) - (row["code_ts"] or 0) > CODE_TTL:
            return False
        conn.execute("UPDATE students SET verified_ts=?, granted=1, code=NULL WHERE email=?",
                     (int(time.time()), e))
        return True
