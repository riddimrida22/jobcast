"""Transactional email via Resend's HTTP API. Env-driven, so no key lives in the repo:

  RESEND_API_KEY      - re_... ; when absent, send() is a dry run (logs, sends nothing)
  JOBCAST_EMAIL_FROM  - verified sender, e.g. "JobBreak <alerts@jobbreak.ai>"

Mirrors payments/advice: the mechanism is always wired; a missing key degrades to a safe
no-op instead of failing. Uses the standard library only (no extra dependency)."""

import os
import sys
import json
import urllib.request
import urllib.error
from typing import Tuple

_API = "https://api.resend.com/emails"
_DEFAULT_FROM = "JobBreak <alerts@send.jobbreak.ai>"   # the Resend-verified sending subdomain


def configured() -> bool:
    return bool(os.environ.get("RESEND_API_KEY"))


def sender() -> str:
    return os.environ.get("JOBCAST_EMAIL_FROM") or _DEFAULT_FROM


def send(to: str, subject: str, text: str, html: str = "") -> Tuple[bool, str]:
    """Send one email. Returns (ok, info). With no API key this is a dry run that logs a
    one-line summary and reports success, so callers and tests work unchanged."""
    to = (to or "").strip()
    if not to:
        return False, "no_recipient"
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        print(f"[emailer] DRY RUN -> {to} | {subject}", file=sys.stderr, flush=True)
        return True, "dry-run"
    body = {"from": sender(), "to": [to], "subject": subject, "text": text}
    if html:
        body["html"] = html
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(_API, data=data, method="POST", headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = resp.read().decode("utf-8", "replace")
            ok = 200 <= resp.status < 300
            return ok, payload[:200]
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200] if hasattr(e, "read") else str(e)
        print(f"[emailer] send failed {e.code}: {detail}", file=sys.stderr, flush=True)
        return False, f"http_{e.code}"
    except Exception as e:  # noqa: BLE001
        print(f"[emailer] send error: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return False, "error"
