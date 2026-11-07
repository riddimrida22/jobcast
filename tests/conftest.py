import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from riskcore import load_default_engine  # noqa: E402
from server import create_app  # noqa: E402


@pytest.fixture
def engine():
    return load_default_engine()


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()
