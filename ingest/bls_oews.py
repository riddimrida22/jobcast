"""NOT IN USE. Verified 2026-11-06: the BLS public API does not serve OEWS even with a
valid registration key (every OEWS series returns "No Data Available"). Wages are ingested
from the OEWS national Excel files instead - see ingest/oews_files.py. This module is kept
for reference and in case BLS adds OEWS to the API later.

Pull OEWS employment and wages from the BLS API and derive local demand trend and the
occupation wage trend. Requires a BLS registration key (env JOBCAST_BLS_KEY).

Series ID format (confirmed against BLS code tables):
  OEU <areatype:1> <area:7> <industry:6=000000> <occupation:6> <datatype:2>
  areatype N=national, M=metro; national area=0000000; metro area="00"+5-digit CBSA.
  datatype 01=employment, 13=annual median wage.
"""

import os
from typing import Dict, Any, List, Optional
from .common import bls_series, bls_annual_values

EMP, MED_WAGE = "01", "13"
NATIONAL = ("N", "0000000")

# Growth thresholds (percent change over 5 years) for the local demand trend.
GROW_PCT, DECLINE_PCT = 5.0, -5.0


def occ6(soc6: str) -> str:
    return soc6.replace("-", "")


def series_id(areatype: str, area: str, soc6: str, datatype: str) -> str:
    return f"OEU{areatype}{area}000000{occ6(soc6)}{datatype}"


def metro_area(cbsa: str) -> str:
    return "00" + str(cbsa)[-5:]


def _chunks(seq: List[str], n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def self_test(key: str, base_year: int = 2024) -> None:
    """Verify the key + series format against known national totals before a bulk pull."""
    ids = [series_id("N", "0000000", "00-0000", EMP),      # all occupations, employment
           series_id("N", "0000000", "15-1252", MED_WAGE)] # software developers, median wage
    resp = bls_series(ids, base_year, base_year, api_key=key)
    vals = bls_annual_values(resp)
    print("self-test:")
    for sid in ids:
        print(" ", sid, "->", vals.get(sid))


def attach_oews(occupations: Dict[str, Dict[str, Any]], soc6_list: List[str],
                metros: Dict[str, str], key: str, base_year: int,
                cpi_ratio: Optional[float]) -> Dict[str, int]:
    """For each soc6, pull national median wage (base and base-5) and metro employment
    (base and base-5) + metro median wage, then write onto every occupation with that soc6:
      median_wage_national, wage_trend_5yr_real_pct, metros{cbsa:{employment,median_wage,demand_trend}}.
    Returns coverage counts."""
    y0 = base_year - 5
    # Build the series set.
    wanted: List[str] = []
    for soc6 in soc6_list:
        wanted.append(series_id("N", "0000000", soc6, MED_WAGE))
        for cbsa in metros:
            area = metro_area(cbsa)
            wanted.append(series_id("M", area, soc6, EMP))
            wanted.append(series_id("M", area, soc6, MED_WAGE))

    values: Dict[str, Dict[str, float]] = {}
    for batch in _chunks(sorted(set(wanted)), 50):
        resp = bls_series(batch, y0, base_year, api_key=key)
        values.update(bls_annual_values(resp))

    def val(sid: str, year: int) -> Optional[float]:
        return values.get(sid, {}).get(str(year))

    stats = {"national_wage": 0, "metro": 0}
    # Group occupations by soc6 so detailed O*NET codes share the OEWS figures.
    by_soc6: Dict[str, List[Dict[str, Any]]] = {}
    for occ in occupations.values():
        by_soc6.setdefault(occ.get("soc6") or occ["soc"], []).append(occ)

    for soc6, occs in by_soc6.items():
        nat_wage = val(series_id("N", "0000000", soc6, MED_WAGE), base_year)
        nat_wage_0 = val(series_id("N", "0000000", soc6, MED_WAGE), y0)
        wage_trend = None
        if nat_wage and nat_wage_0 and cpi_ratio:
            real_past = nat_wage_0 * cpi_ratio
            wage_trend = round((nat_wage / real_past - 1) * 100, 1)
        metros_out: Dict[str, Dict[str, Any]] = {}
        for cbsa in metros:
            area = metro_area(cbsa)
            emp = val(series_id("M", area, soc6, EMP), base_year)
            emp0 = val(series_id("M", area, soc6, EMP), y0)
            wage = val(series_id("M", area, soc6, MED_WAGE), base_year)
            trend = "stable"
            if emp and emp0:
                chg = (emp / emp0 - 1) * 100
                trend = "growing" if chg >= GROW_PCT else "declining" if chg <= DECLINE_PCT else "stable"
            if emp or wage:
                metros_out[cbsa] = {"employment": emp, "median_wage": wage, "demand_trend": trend}
                stats["metro"] += 1
        if nat_wage:
            stats["national_wage"] += 1
        for occ in occs:
            occ["median_wage_national"] = nat_wage
            occ["wage_trend_5yr_real_pct"] = wage_trend
            occ["metros"] = metros_out
    return stats


if __name__ == "__main__":
    key = os.environ.get("JOBCAST_BLS_KEY")
    if not key:
        raise SystemExit("set JOBCAST_BLS_KEY to run the self-test")
    self_test(key)
