"""Country registry: the per-country facts the engine and UI need beyond the
(country-invariant) AI/robot exposure. Exposure is task-intrinsic and reused across
countries via an occupation crosswalk; what varies by country is pay, currency, local
demand, geography, and occupation naming.

US is the default and the only country with a full data snapshot today. Other countries
are added by shipping a wage overlay (data/overlays/<code>_wages.json): a map of the
country's occupation median pay keyed to the shared O*NET SOC, built from an official
source (e.g. UK ONS ASHE Table 14) via a documented crosswalk. Until an overlay exists,
the engine withholds pay for that country rather than mislabel US dollars in another
currency.
"""

from typing import Dict, Any, Optional

DEFAULT = "us"

# code -> country facts. `wage_source` names the official pay source for auditing;
# `geography` is how the UI asks for location (us: zip->metro; others: national to start).
COUNTRIES: Dict[str, Dict[str, Any]] = {
    "us": {
        "name": "United States",
        "currency_code": "USD",
        "currency_symbol": "$",
        "wage_period": "year",
        "wage_source": "BLS OEWS",
        "geography": "zip_metro",
    },
    "uk": {
        "name": "United Kingdom",
        "currency_code": "GBP",
        "currency_symbol": "£",
        "wage_period": "year",
        "wage_source": "ONS ASHE Table 14 (SOC2020, median gross annual)",
        "geography": "national",
    },
}


def resolve(code: Optional[str]) -> str:
    """Normalise a country code to one we support, defaulting to US."""
    c = (code or "").strip().lower()
    return c if c in COUNTRIES else DEFAULT


def info(code: Optional[str]) -> Dict[str, Any]:
    return COUNTRIES[resolve(code)]


def currency(code: Optional[str]) -> Dict[str, str]:
    c = info(code)
    return {"code": c["currency_code"], "symbol": c["currency_symbol"],
            "period": c["wage_period"]}
