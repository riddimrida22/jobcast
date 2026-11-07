"""Parse OEWS national Excel files (downloaded from bls.gov) for median wage and
employment by occupation, and compute the 5-year real wage trend. Used instead of the
BLS API, which does not serve OEWS.

Files (extracted under data/cache/oews/):
  oesm25nat/national_M2025_dl.xlsx  (latest, median wage + employment)
  oesm20nat/national_M2020_dl.xlsx  (five years earlier, for the trend)
Key columns: OCC_CODE (SOC), O_GROUP ("detailed"), TOT_EMP, A_MEDIAN (annual median wage).
"""

import glob
from pathlib import Path
from typing import Dict, Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OEWS_DIR = ROOT / "data" / "cache" / "oews"


def _num(x) -> Optional[float]:
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None   # BLS suppression marks ("*", "#", "**") become None


def load_national(xlsx_path: str) -> Dict[str, Dict[str, Optional[float]]]:
    df = pd.read_excel(xlsx_path, dtype=str)
    out: Dict[str, Dict[str, Optional[float]]] = {}
    for _, r in df.iterrows():
        if r.get("O_GROUP") != "detailed":
            continue
        out[r["OCC_CODE"]] = {"emp": _num(r.get("TOT_EMP")), "median": _num(r.get("A_MEDIAN"))}
    return out


def find_file(pattern: str) -> Optional[str]:
    hits = glob.glob(str(OEWS_DIR / pattern))
    return hits[0] if hits else None


def available() -> bool:
    return bool(find_file("oesm25nat/national_M2025_dl.xlsx"))


def msa_available() -> bool:
    return bool(find_file("oesm25ma/MSA_M2025_dl.xlsx"))


def load_msa(xlsx_path: str):
    """Return ({(cbsa, soc6): {emp, median}}, {cbsa: area_title}) for detailed occupations."""
    df = pd.read_excel(xlsx_path, dtype=str,
                       usecols=["AREA", "AREA_TITLE", "OCC_CODE", "O_GROUP", "TOT_EMP", "A_MEDIAN"])
    df = df[df["O_GROUP"] == "detailed"]
    data: Dict = {}
    names: Dict[str, str] = {}
    for r in df.itertuples(index=False):
        names[r.AREA] = r.AREA_TITLE
        data[(r.AREA, r.OCC_CODE)] = {"emp": _num(r.TOT_EMP), "median": _num(r.A_MEDIAN)}
    return data, names


def build_metro_wages(decline_pct: float = -5.0, grow_pct: float = 5.0):
    """Build {soc6: {cbsa: {employment, median_wage, demand_trend}}} and {cbsa: name},
    using May 2025 for levels and May 2020 for the demand trend (employment change)."""
    cur, names = load_msa(find_file("oesm25ma/MSA_M2025_dl.xlsx"))
    old, _ = load_msa(find_file("oesm20ma/MSA_M2020_dl.xlsx")) if find_file("oesm20ma/MSA_M2020_dl.xlsx") else ({}, {})
    metro_wages: Dict[str, Dict[str, Any]] = {}
    for (cbsa, soc), d in cur.items():
        trend = "stable"
        d0 = old.get((cbsa, soc))
        if d["emp"] and d0 and d0["emp"]:
            chg = (d["emp"] / d0["emp"] - 1) * 100
            trend = "growing" if chg >= grow_pct else "declining" if chg <= decline_pct else "stable"
        metro_wages.setdefault(soc, {})[cbsa] = {
            "employment": d["emp"], "median_wage": d["median"], "demand_trend": trend}
    return metro_wages, names


def attach(occupations: Dict[str, Dict[str, Any]], cpi_ratio: Optional[float]) -> Dict[str, int]:
    """Set median_wage_national, employment_national, and wage_trend_5yr_real_pct on each
    occupation (joined by 6-digit SOC). Returns coverage counts."""
    latest = find_file("oesm25nat/national_M2025_dl.xlsx")
    prior = find_file("oesm20nat/national_M2020_dl.xlsx")
    n_new = load_national(latest) if latest else {}
    n_old = load_national(prior) if prior else {}
    stats = {"wage": 0, "trend": 0}
    for occ in occupations.values():
        soc6 = occ.get("soc")             # occupations dict is keyed/field by 6-digit SOC here
        d = n_new.get(soc6)
        if not d:
            continue
        occ["median_wage_national"] = d["median"]
        occ["employment_national"] = d["emp"]
        stats["wage"] += 1
        d0 = n_old.get(soc6)
        if d["median"] and d0 and d0["median"] and cpi_ratio:
            real_past = d0["median"] * cpi_ratio
            occ["wage_trend_5yr_real_pct"] = round((d["median"] / real_past - 1) * 100, 1)
            stats["trend"] += 1
    return stats
