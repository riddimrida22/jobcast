"""The landing "RIGHT NOW" HUD signals ticker.

A small, curated set of current why-now signals shown as a scrolling strip at the
top of the landing scanner. It is the in-app version of the ad's trendjacking beat:
it makes the moment feel urgent and current without claiming to be a live feed.

Honesty rules (these are the conversion asset, do not break them):
- Every item is a real, defensible signal, phrased qualitatively. We do NOT invent
  precise statistics (fake layoff counts, fake dates). Where a hard number appears it
  is one that is independently checkable (e.g. the headline AI IPO valuation).
- The strip is labelled "curated" and carries an "updated" date (AS_OF) so it never
  pretends to be real-time. Refresh ITEMS and AS_OF when the news moves.
- One item deliberately bridges to the rigor (O*NET/BLS) so the HUD never drifts into
  pure rage-bait: the drama points straight at the sourced method.

Kept deterministic and dependency-free so it costs nothing to serve and can never
break a page render.
"""

from __future__ import annotations

from typing import Dict, List

# Refresh this date whenever ITEMS is updated, so the strip stays honest about currency.
AS_OF = "2026-11-22"

# kind  : one short uppercase label for the HUD chip (the signal's category).
# text  : the signal, in one sayable line. Qualitative unless the number is checkable.
# source: where it comes from, shown small as attribution (never a fake citation).
ITEMS: List[Dict[str, str]] = [
    {
        "kind": "MARKETS",
        "text": "Anthropic's $1.8T IPO is the largest AI listing ever — the market is betting automation accelerates.",
        "source": "public markets",
    },
    {
        "kind": "LAYOFFS",
        "text": "Companies are again naming AI and automation in this quarter's job cuts.",
        "source": "business news",
    },
    {
        "kind": "CAPABILITY",
        "text": "Frontier AI now helps build the next AI — each generation ships faster than the last.",
        "source": "AI research",
    },
    {
        "kind": "YOUR DATA",
        "text": "O*NET lists the real tasks in 1,000+ jobs. We score how many a machine can already do.",
        "source": "O*NET · BLS",
    },
    {
        "kind": "THE CLOCK",
        "text": "For most roles the question isn't 'if' — it's how much, and when.",
        "source": "exposure research",
    },
]


def signals() -> Dict[str, object]:
    """Return the curated ticker payload for the landing template.

    Shape: {"as_of": "YYYY-MM-DD", "items": [{kind, text, source}, ...]}.
    Always returns a usable dict; never raises.
    """
    return {"as_of": AS_OF, "items": list(ITEMS)}
