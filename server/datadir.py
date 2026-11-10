"""Resolve the directory for durable data (analytics, watches, subscriber records).

Priority:
  1. JOBCAST_DATA_DIR, if set explicitly.
  2. /var/data, when it exists - i.e. a Render persistent disk mounted there. This
     lets a mounted disk "just work" with no extra env var.
  3. The repo's data/ folder (local dev; resets on redeploy in production).
"""

import os
from pathlib import Path

_REPO_DATA = Path(__file__).resolve().parents[1] / "data"
_MOUNTED_DISK = Path("/var/data")


def data_dir() -> Path:
    base = os.environ.get("JOBCAST_DATA_DIR")
    if base:
        d = Path(base)
    elif _MOUNTED_DISK.is_dir():
        d = _MOUNTED_DISK
    else:
        d = _REPO_DATA
    d.mkdir(parents=True, exist_ok=True)
    return d
