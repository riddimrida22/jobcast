"""Validate a data snapshot before it is used. Checks required fields, value ranges, and
family coverage. Exit 1 on any problem.

Usage (from the repo root):
  python tools/verify_snapshot.py
  python tools/verify_snapshot.py data/fixtures/snapshot.json
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from riskcore.snapshot import Snapshot  # noqa: E402


def verify(path: str):
    problems = []
    snap = Snapshot.from_file(path)
    if snap.base_year is None:
        problems.append("missing base_year")
    occs = snap.all_occupations()
    if not occs:
        problems.append("no occupations")
    for occ in occs:
        where = occ.get("soc", "?")
        if not occ.get("tasks"):
            problems.append(f"{where}: no tasks")
        for t in occ.get("tasks", []):
            for axis in ("ai", "robo"):
                v = t.get(axis)
                if v is None or not (0.0 <= v <= 1.0):
                    problems.append(f"{where}/{t.get('id')}: {axis} out of range: {v}")
        if snap.family_name(snap.family_code(where)) == snap.family_code(where):
            problems.append(f"{where}: family {snap.family_code(where)} not named in families")
    return problems


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "data" / "fixtures" / "snapshot.json")
    problems = verify(path)
    if problems:
        for p in problems:
            print(f"PROBLEM {p}")
        print(f"\n{len(problems)} problem(s) in {path}.")
        return 1
    print(f"snapshot OK: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
