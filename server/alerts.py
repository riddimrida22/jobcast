"""Outlook-shift detector: the engine behind "we'll tell you when your job's outlook
changes". For each armed watch it compares the job's current outlook in the live data
snapshot to the value stored when the watch was last set or last notified, and emails the
person only when the change clears a threshold (so routine noise never triggers a message).

The two tracked signals are both occupation-level and come straight from the snapshot the
app serves, so an alert says exactly what the site shows:
  - exposure: how automatable the job's tasks are, max(AI, robotics) x 100 (0..100)
  - demand:   BLS projected % change in employment for the occupation
"""

import os
import sys
import time
from typing import Dict, Any, Optional, Tuple

from . import store, emailer

EXPOSURE_THRESHOLD = 3.0     # points of exposure movement that count as a shift
DEMAND_THRESHOLD = 3.0       # points of projected-demand movement that count as a shift


def _base_url() -> str:
    return (os.environ.get("JOBCAST_BASE_URL") or "https://jobbreak.ai").rstrip("/")


def outlook(occ: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """(exposure, demand) for an occupation, using the same numbers the UI shows."""
    if not occ:
        return None, None
    ai = occ.get("ai") or 0.0
    robo = occ.get("robo") or 0.0
    exposure = round(max(ai, robo) * 100, 1)
    demand = occ.get("projection_pct")
    if demand is not None:
        demand = round(float(demand), 1)
    return exposure, demand


def _describe(title: str, soc: str, old_exp, new_exp, old_dem, new_dem) -> Tuple[str, str, str]:
    url = f"{_base_url()}/jobs/{soc}"
    lines = []
    if old_exp is not None and new_exp is not None and abs(new_exp - old_exp) >= EXPOSURE_THRESHOLD:
        direction = "more exposed to automation" if new_exp > old_exp else "less exposed to automation"
        lines.append(f"Automation exposure moved from {old_exp:g} to {new_exp:g} out of 100 "
                     f"({direction}).")
    if old_dem is not None and new_dem is not None and abs(new_dem - old_dem) >= DEMAND_THRESHOLD:
        direction = "up" if new_dem > old_dem else "down"
        lines.append(f"Projected demand to 2030 moved {direction}, from {old_dem:g}% to {new_dem:g}%.")
    change = " ".join(lines) or "The outlook for this role has changed."
    subject = f"Your JobBreak outlook changed: {title}"
    text = (
        f"The automation outlook for {title} has shifted.\n\n"
        f"{change}\n\n"
        f"This is based on the latest data, not a prediction about you personally. "
        f"See the full, sourced read and what to do next:\n{url}\n"
    )
    html = (
        f"<p>The automation outlook for <strong>{title}</strong> has shifted.</p>"
        f"<p>{change}</p>"
        f"<p>This is based on the latest data, not a prediction about you personally. "
        f'<a href="{url}">See the full, sourced read and what to do next.</a></p>'
    )
    return subject, text, html


def run_check(engine, threshold: float = EXPOSURE_THRESHOLD, dry_run: bool = False) -> Dict[str, int]:
    """Walk every armed watch, send on a real shift, and update baselines. Returns counts.

    dry_run forces the no-send path even if an email key is configured (for safe testing)."""
    watches = store.active_watches(with_soc=True)
    now = int(time.time())
    sent = baselined = unchanged = missing = 0
    for w in watches:
        occ = engine.snapshot.occupation(w["soc"])
        if not occ:
            missing += 1
            continue
        new_exp, new_dem = outlook(occ)
        old_exp, old_dem = w.get("last_exposure"), w.get("last_demand")
        if old_exp is None:                         # first time seen: set the baseline, no email
            store.set_state(w["id"], new_exp, new_dem)
            baselined += 1
            continue
        exp_shift = new_exp is not None and abs(new_exp - old_exp) >= threshold
        dem_shift = (old_dem is not None and new_dem is not None
                     and abs(new_dem - old_dem) >= DEMAND_THRESHOLD)
        if not (exp_shift or dem_shift):
            unchanged += 1
            continue
        title = occ.get("title", w["soc"])
        subject, text, html = _describe(title, w["soc"], old_exp, new_exp, old_dem, new_dem)
        link = f"{_base_url()}/unsubscribe?t={w.get('token','')}"
        text += f"\nStop these alerts: {link}\n"
        html += f'<p style="color:#888;font-size:12px"><a href="{link}">Stop these alerts</a></p>'
        if dry_run:
            print(f"[alerts] WOULD SEND -> {w['email']} | {subject}", file=sys.stderr, flush=True)
            ok = True
        else:
            ok, _info = emailer.send(w["email"], subject, text, html)
        if ok:
            store.set_state(w["id"], new_exp, new_dem, notified_ts=now)
            sent += 1
    return {"watches": len(watches), "sent": sent, "baselined": baselined,
            "unchanged": unchanged, "missing": missing}
