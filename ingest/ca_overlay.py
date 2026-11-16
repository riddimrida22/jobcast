"""Build the Canada wage overlay, by joining the Dais/Brookfield NOC2021<->O*NET
crosswalk to Government of Canada Job Bank national median wages (NOC 2021).

Inputs (both committed, citable):
  config/crosswalks/noc2021_onet26.csv          Dais/Brookfield NOC2021 <-> O*NET v26
  data/sources/ca/jobbank_noc_national_2025.json Job Bank national median by NOC (CAD)

Output:
  data/overlays/ca_wages.json                    {source, soc_median: {onet_soc: CAD}}

The crosswalk maps 8-digit O*NET-SOC to 5-digit NOC. We key the overlay by the full
O*NET SOC (what the engine looks up first). Where one O*NET code maps to several NOCs,
the first candidate carrying a national median is used. Job Bank hourly medians are
annualized at 2080 h/yr in the source file; annual-flagged occupations are used as-is.
Run: python -m ingest.ca_overlay
"""
import csv
import json
import re
from pathlib import Path


def _clean_fr_title(t: str) -> str:
    """Turn an official NOC French unit-group name into a consumer-friendly title:
    keep the masculine/feminine doublet (correct Quebec form) but drop parenthetical
    qualifiers and any ' et <secondary group>' tail, which make the group names very long.
    e.g. 'Infirmiers autorises/infirmieres autorisees et infirmiers psychiatriques ...'
         -> 'Infirmiers autorises/infirmieres autorisees'."""
    t = re.sub(r"\s*\([^)]*\)", "", t or "")      # drop "(...)" qualifiers
    t = re.split(r"\s+et\s+", t, maxsplit=1)[0]    # keep the primary group before " et "
    return t.strip()

ROOT = Path(__file__).resolve().parents[1]
CROSSWALK = ROOT / "config" / "crosswalks" / "noc2021_onet26.csv"
JOBBANK = ROOT / "data" / "sources" / "ca" / "jobbank_noc_national_2025.json"
OUT = ROOT / "data" / "overlays" / "ca_wages.json"


def build(verbose: bool = True) -> dict:
    nocs = json.loads(JOBBANK.read_text(encoding="utf-8"))
    meta = nocs.get("_meta", {})

    xw = {}  # onet 8-digit -> [noc5, ...] in file order
    with open(CROSSWALK, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            onet = (row["onet"] or "").strip()
            noc = (row["noc"] or "").strip().zfill(5)
            if onet:
                xw.setdefault(onet, []).append(noc)

    soc_median, soc_title_fr, missing = {}, {}, []
    for onet, cands in xw.items():
        med = None
        for c in cands:
            rec = nocs.get(c)
            if isinstance(rec, dict) and rec.get("annual_cad"):
                med = round(float(rec["annual_cad"]))
                # French NOC title from the same unit group (Canadian French, for ca+fr).
                tf = _clean_fr_title(rec.get("title_fr") or "")
                if tf:
                    soc_title_fr[onet] = tf
                break
        if med:
            soc_median[onet] = med
        else:
            missing.append(onet)

    overlay = {
        "country": "ca",
        "currency": "CAD",
        "source": meta.get("source"),
        "source_url": meta.get("url"),
        "measure": meta.get("measure"),
        "crosswalk": "config/crosswalks/noc2021_onet26.csv (Dais/Brookfield NOC2021<->O*NET v26)",
        "soc_median": soc_median,
        "soc_title_fr": soc_title_fr,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(overlay, ensure_ascii=False, indent=0), encoding="utf-8")

    if verbose:
        print(f"O*NET codes in crosswalk: {len(xw)} | priced: {len(soc_median)} | unpriced: {len(missing)}")
        print(f"wrote {OUT.relative_to(ROOT)}")
    return overlay


if __name__ == "__main__":
    build()
