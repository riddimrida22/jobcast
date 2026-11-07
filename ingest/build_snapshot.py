"""Build a real snapshot from O*NET (structure + work context) and Eloundou (AI exposure),
in the shape riskcore consumes. Wages/local-market data (OEWS) are attached in a later
step once a BLS API key or the OEWS files are available.

Usage (from the repo root):
  python -m ingest.build_snapshot
  python -m ingest.build_snapshot --limit 50     # a small first build
"""

import argparse
import os
from typing import Dict, Any, List

from . import onet, bls_cpi, oews_files, zip_metro, exposure
from .common import download_to_cache, write_snapshot

ELOUNDOU_URL = "https://raw.githubusercontent.com/openai/GPTs-are-GPTs/main/data/occ_level.csv"

# The 23 SOC major groups (the general field), keyed by the 2-digit prefix.
SOC_MAJOR_GROUPS = {
    "11": "Management", "13": "Business and Financial Operations",
    "15": "Computer and Mathematical", "17": "Architecture and Engineering",
    "19": "Life, Physical, and Social Science", "21": "Community and Social Service",
    "23": "Legal", "25": "Educational Instruction and Library",
    "27": "Arts, Design, Entertainment, Sports, and Media",
    "29": "Healthcare Practitioners and Technical", "31": "Healthcare Support",
    "33": "Protective Service", "35": "Food Preparation and Serving Related",
    "37": "Building and Grounds Cleaning and Maintenance", "39": "Personal Care and Service",
    "41": "Sales and Related", "43": "Office and Administrative Support",
    "45": "Farming, Fishing, and Forestry", "47": "Construction and Extraction",
    "49": "Installation, Maintenance, and Repair", "51": "Production",
    "53": "Transportation and Material Moving", "55": "Military Specific",
}

SOURCES = [
    {"id": "onet", "name": "O*NET", "version": "29.1",
     "use": "Occupation titles, SOC codes, tasks, work context, job zones, related occupations."},
    {"id": "eloundou_2023", "name": "Eloundou et al. (2023), GPTs are GPTs", "version": "2023",
     "use": "AI/software task exposure (measure beta), human annotators."},
    {"id": "onet_work_context", "name": "O*NET Work Context", "version": "29.1",
     "use": "Physical/manual variables for the robotics-exposure proxy."},
    {"id": "bls_cpi", "name": "BLS CPI-U", "version": "live",
     "use": "Inflation adjustment for the wage-trajectory signal."},
]


def build(base_year: int = 2025, limit: int = 0) -> Dict[str, Any]:
    download_to_cache(ELOUNDOU_URL, "eloundou_occ_level.csv")
    occupations = onet.fetch_and_parse()
    related = onet.build_related(onet.cached_zip())
    coverage = exposure.attach_exposure(occupations)
    print("exposure coverage:", coverage)

    if limit:
        occupations = dict(list(occupations.items())[:limit])

    # Wages/employment from OEWS national files (the BLS API does not serve OEWS).
    cpi = bls_cpi.fetch_cpi(base_year)
    cpi_index = cpi.get("index", {})
    cpi_ratio = None
    if str(base_year) in cpi_index and str(base_year - 5) in cpi_index:
        cpi_ratio = cpi_index[str(base_year)] / cpi_index[str(base_year - 5)]
    have_wages = False
    if oews_files.available():
        oews_stats = oews_files.attach(occupations, cpi_ratio)
        print("OEWS national coverage:", oews_stats)
        have_wages = oews_stats.get("wage", 0) > 0
    else:
        print("OEWS national files not in data/cache/oews/: skipping wages.")

    metro_wages, metro_names = {}, {}
    if oews_files.msa_available():
        print("parsing OEWS metro files (this takes ~1 min) ...")
        metro_wages, metro_names = oews_files.build_metro_wages()
        print(f"metro wages: {len(metro_names)} metros, {len(metro_wages)} occupations")

    zip_map = {}
    if metro_names and zip_metro.available():
        zip_map = zip_metro.build_zip_map(set(metro_names.keys()))
        print(f"zip -> metro: {len(zip_map)} ZIPs mapped")

    # Adjacency from Related Occupations, each with its exposure so the engine can filter.
    def adj_for(code: str) -> List[Dict[str, Any]]:
        out = []
        for rc in related.get(code, []):
            occ = occupations.get(rc)
            if occ and "ai" in occ:
                out.append({"soc": rc, "title": occ["title"],
                            "ai": occ["ai"], "robo": occ["robo"]})
        return out

    families = {code.split("-")[0]: SOC_MAJOR_GROUPS.get(code.split("-")[0], code.split("-")[0])
                for code in occupations}

    occ_list = []
    for code, occ in occupations.items():
        occ_list.append({
            "soc": code, "soc6": occ["soc"], "title": occ["title"], "job_zone": occ["job_zone"],
            "aliases": occ["aliases"],
            "ai": occ.get("ai"), "robo": occ.get("robo"),   # occupation-level fallback
            "tasks": [{"id": t["id"], "name": t["name"], "ai": t["ai"], "robo": t["robo"]}
                      for t in occ["tasks"]],
            "adjacent": adj_for(code),
            "metros": {},
            "median_wage_national": occ.get("median_wage_national"),
            "employment_national": occ.get("employment_national"),
            "wage_trend_5yr_real_pct": occ.get("wage_trend_5yr_real_pct"),
        })

    notice = None if have_wages else ("Exposure from O*NET 29.1 and Eloundou et al. (2023). "
                                      "Wage data not yet loaded.")
    snapshot = {
        "base_year": base_year,
        "development_notice": notice,
        "cpi": cpi,
        "metros": {"US": "United States (national)", **metro_names},
        "zip_to_metro": {"default": "US", "map": {**{c: c for c in metro_names}, **zip_map}},
        "metro_wages": metro_wages,
        "families": families,
        "occupations": occ_list,
        "sources": SOURCES + ([{"id": "bls_oews", "name": "BLS OEWS", "version": "May 2025",
                                "use": "National median wage and employment; 5-year real wage trend."}]
                              if have_wages else []),
    }
    write_snapshot(snapshot, licensed=have_wages)
    return snapshot


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-year", type=int, default=2025)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    build(args.base_year, args.limit)
