"""Build the UK wage overlay the engine consumes, by joining the curated
O*NET-SOC6 -> SOC2020 crosswalk to ONS ASHE median annual pay (SOC2020).

Inputs (both committed, citable):
  config/crosswalks/onet_soc6_to_soc2020.json   curated crosswalk
  data/sources/uk/ashe_t14_7a_2024.json         ONS ASHE Table 14.7a median £

Output:
  data/overlays/uk_wages.json                   {source, edition, soc_median: {onet_soc6: £}}

The engine (riskcore/engine.py) looks pay up by the occupation's full SOC then its
SOC6 base, so keying the overlay by SOC6 covers every O*NET detail variant (.00/.01/...).
Run: python -m ingest.uk_overlay
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CROSSWALK = ROOT / "config" / "crosswalks" / "onet_soc6_to_soc2020.json"
ONS = ROOT / "data" / "sources" / "uk" / "ashe_t14_7a_2024.json"
OUT = ROOT / "data" / "overlays" / "uk_wages.json"


def build(verbose: bool = True) -> dict:
    xw = json.loads(CROSSWALK.read_text(encoding="utf-8"))["crosswalk"]
    ons = json.loads(ONS.read_text(encoding="utf-8"))
    meta = ons.get("_meta", {})

    soc_median, audit, missing = {}, [], []
    for soc6, soc2020 in xw.items():
        row = ons.get(soc2020)
        if not row or not row.get("median_annual_gbp"):
            missing.append((soc6, soc2020))
            continue
        gbp = round(float(row["median_annual_gbp"]))
        soc_median[soc6] = gbp
        audit.append((soc6, soc2020, gbp, row.get("title", "")))

    overlay = {
        "country": "uk",
        "currency": "GBP",
        "source": meta.get("source"),
        "edition": meta.get("edition"),
        "source_url": meta.get("url"),
        "crosswalk": "config/crosswalks/onet_soc6_to_soc2020.json",
        "soc_median": soc_median,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(overlay, ensure_ascii=False, indent=0), encoding="utf-8")

    if verbose:
        print(f"crosswalk entries: {len(xw)} | priced: {len(soc_median)} | missing ONS median: {len(missing)}")
        if missing:
            print("  missing (SOC2020 suppressed/absent):", missing)
        print(f"wrote {OUT.relative_to(ROOT)}")
    return overlay


if __name__ == "__main__":
    build()
