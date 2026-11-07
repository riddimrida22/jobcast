"""riskcore: the deterministic job-automation-exposure engine for Jobcast.

Design rule (see CLAUDE.md and BUILD_PLAN.md): this package computes every number from
the data snapshot and the config weights. No language model is involved here. The engine
is pure Python with no network or disk I/O beyond loading the snapshot and config once,
so a given (profile, snapshot, config) always produces the same result.
"""

from .model import Profile
from .snapshot import Snapshot
from .engine import Engine, load_default_engine

__all__ = ["Profile", "Snapshot", "Engine", "load_default_engine"]
