"""Production entrypoint. The serving app needs only Flask (the engine is pure standard
library); pandas/scipy are only for offline ingestion and are not imported here.

  gunicorn wsgi:app --bind 0.0.0.0:$PORT
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Default to the committed demo snapshot unless overridden.
os.environ.setdefault("JOBCAST_SNAPSHOT", str(ROOT / "data" / "demo" / "snapshot.json"))

from server import create_app  # noqa: E402

app = create_app()
