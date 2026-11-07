"""Build a ZIP (ZCTA) -> metro (CBSA) map using current Census geography, so CBSA codes
match the OEWS wage data (the older 2010 ZCTA-CBSA file used retired codes, e.g. LA 31100).

Join: 2020 ZCTA -> county (dominant county by land area) -> 2023 county -> CBSA.
Only ZIPs whose metro has wage data are kept; the rest fall back to the national read.

Files (under data/cache/zip/):
  zcta_county_2020.txt         pipe-delimited ZCTA-to-county (Census rel2020)
  cbsa_delineation_2023.xlsx   OMB/Census county-to-CBSA delineation (current codes)
"""

from pathlib import Path
from typing import Dict, Set

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ZCTA_COUNTY = ROOT / "data" / "cache" / "zip" / "zcta_county_2020.txt"
DELINEATION = ROOT / "data" / "cache" / "zip" / "cbsa_delineation_2023.xlsx"


def available() -> bool:
    return ZCTA_COUNTY.exists() and DELINEATION.exists()


def _county_to_cbsa() -> Dict[str, str]:
    df = pd.read_excel(DELINEATION, dtype=str, skiprows=2)
    out: Dict[str, str] = {}
    for _, r in df.iterrows():
        st, co, cbsa = r.get("FIPS State Code"), r.get("FIPS County Code"), r.get("CBSA Code")
        if st and co and cbsa and str(cbsa).strip().isdigit():
            out[str(st).zfill(2) + str(co).zfill(3)] = str(cbsa).strip()
    return out


def build_zip_map(valid_cbsas: Set[str]) -> Dict[str, str]:
    county_cbsa = _county_to_cbsa()
    best: Dict[str, tuple] = {}   # zcta5 -> (area, cbsa)
    with open(ZCTA_COUNTY, encoding="utf-8-sig") as fh:
        header = fh.readline().rstrip("\n").split("|")
        iz = header.index("GEOID_ZCTA5_20")
        ic = header.index("GEOID_COUNTY_20")
        ia = header.index("AREALAND_PART")
        for line in fh:
            c = line.rstrip("\n").split("|")
            if len(c) <= max(iz, ic, ia):
                continue
            z, county = c[iz], c[ic]
            if not z or not county:
                continue
            cbsa = county_cbsa.get(county)
            if not cbsa or cbsa not in valid_cbsas:
                continue
            try:
                area = int(c[ia])
            except ValueError:
                area = 0
            if z not in best or area > best[z][0]:
                best[z] = (area, cbsa)
    return {z: v[1] for z, v in best.items()}
