"""Run the dev server:  python -m server   (from the repo root).

Options via environment:
  JOBCAST_PORT                 port (default 8090)
  JOBCAST_DEV_PLAN_HEADER=1    honor the X-Plan header to unlock paid tiers (dev only)
"""

import os
from server import create_app

if __name__ == "__main__":
    port = int(os.environ.get("JOBCAST_PORT", "8090"))
    create_app().run(host="127.0.0.1", port=port, debug=True)
