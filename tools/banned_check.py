"""Fail if any user-facing string uses a banned word, phrase, or character.

Scans HTML templates and Python source for the substrings in contracts/banned_words.json.
Exit 1 on any banned hit. With --review it also lists review-word warnings.

Usage (from the repo root):
  python tools/banned_check.py
  python tools/banned_check.py --review
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_GLOBS = ["server/templates/*.html", "server/*.py", "riskcore/*.py"]


def load_rules():
    with open(ROOT / "contracts" / "banned_words.json", "r", encoding="utf-8") as fh:
        rules = json.load(fh)
    return rules.get("banned_substrings", []), rules.get("review_substrings", [])


def scan():
    banned, review = load_rules()
    files = []
    for g in SCAN_GLOBS:
        files.extend(sorted(ROOT.glob(g)))
    banned_hits, review_hits = [], []
    for path in files:
        if path.name == "banned_check.py":
            continue
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            for b in banned:
                if b.lower() in low:
                    banned_hits.append((path.relative_to(ROOT), i, b))
            for r in review:
                if r.lower() in low:
                    review_hits.append((path.relative_to(ROOT), i, r))
    return banned_hits, review_hits


def main():
    banned_hits, review_hits = scan()
    if "--review" in sys.argv:
        for path, line, word in review_hits:
            print(f"REVIEW {path}:{line}  '{word}'")
    for path, line, word in banned_hits:
        shown = word.encode("unicode_escape").decode("ascii")
        print(f"BANNED {path}:{line}  '{shown}'")
    if banned_hits:
        print(f"\n{len(banned_hits)} banned hit(s).")
        return 1
    print(f"0 banned hits. {len(review_hits)} review-word warning(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
