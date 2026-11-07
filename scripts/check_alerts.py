"""Run the outlook-shift check once and print a summary. Point a scheduler (Render Cron
Job, cron, Task Scheduler) at this after each data refresh and on a regular cadence.

    # real send (needs RESEND_API_KEY set):
    python scripts/check_alerts.py
    # safe test (never sends, just reports what it would do):
    python scripts/check_alerts.py --dry-run

Reads the same snapshot the web app serves (JOBCAST_SNAPSHOT) and the same watch store
(JOBCAST_DATA_DIR), so a run here matches what users would be told."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from riskcore.engine import load_default_engine  # noqa: E402
from server import alerts                          # noqa: E402


def main() -> int:
    dry = "--dry-run" in sys.argv or "-n" in sys.argv
    engine = load_default_engine()
    summary = alerts.run_check(engine, dry_run=dry)
    mode = "DRY RUN" if dry else "LIVE"
    print(f"[check_alerts] {mode}: " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
