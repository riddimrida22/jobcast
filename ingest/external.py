"""Independent external exposure measures and SOC-keyed BLS projections.

These are development-time loaders (used by the calibration backtest and the snapshot build),
not runtime server code. Each reads a cached public file under data/cache/exposure/ and
returns a plain {6-digit SOC: value} dict, degrading to {} if the file is absent so the
pipeline never hard-fails on a missing optional source.

Sources:
  - AIOE: Felten, Raj & Seamans AI Occupational Exposure (AIOE_DataAppendix.xlsx, Appendix A),
    SOC-2010. Used ONLY for convergent validity (a measure we do not fit on), so a direct
    6-digit SOC join to our SOC-2018 data - which matches the many codes unchanged across the
    revision - is sufficient; the handful of split/renumbered codes simply drop out.
  - BLS Employment Projections (occupation.xlsx, Table 1.2), SOC-2018: proper SOC-keyed
    projected employment change, replacing the older occupation-NAME match.
  - Webb (2020) patent-based exposure: no cleanly public per-occupation file exists (the
    author's data link is email-gated); documented as a gap. load_webb() returns {} unless a
    prepared data/cache/exposure/webb_soc.csv (columns soc6,value) is dropped in by hand.
"""

import csv
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]
EXPOSURE_DIR = ROOT / "data" / "cache" / "exposure"
AIOE_XLSX = EXPOSURE_DIR / "AIOE_DataAppendix.xlsx"
EP_XLSX = EXPOSURE_DIR / "ep_occupation.xlsx"
WEBB_CSV = EXPOSURE_DIR / "webb_soc.csv"


def _soc6(code: str) -> str:
    code = (code or "").strip()
    return code.split(".")[0]


def load_aioe(path: Path = AIOE_XLSX) -> Dict[str, float]:
    """6-digit SOC -> AIOE score (Felten-Raj-Seamans). {} if the workbook is absent."""
    if not path.exists():
        return {}
    import pandas as pd
    df = pd.read_excel(path, sheet_name="Appendix A", dtype=str)
    out: Dict[str, float] = {}
    for _, r in df.iterrows():
        try:
            out[_soc6(r["SOC Code"])] = float(r["AIOE"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def load_ep_projections(path: Path = EP_XLSX) -> Dict[str, float]:
    """6-digit SOC -> projected employment change percent (BLS EP, Table 1.2 line items).
    {} if the workbook is absent."""
    if not path.exists():
        return {}
    import pandas as pd
    df = pd.read_excel(path, sheet_name="Table 1.2", dtype=str, header=1)
    code_col = next(c for c in df.columns if "Matrix code" in str(c))
    type_col = next(c for c in df.columns if "Occupation type" in str(c))
    pct_col = next(c for c in df.columns if "change, percent" in str(c))
    out: Dict[str, float] = {}
    for _, r in df.iterrows():
        if str(r.get(type_col)).strip() != "Line item":
            continue
        code = _soc6(str(r.get(code_col)))
        if not code or "-" not in code:
            continue
        try:
            out[code] = float(str(r.get(pct_col)).replace(",", ""))
        except (TypeError, ValueError):
            continue
    return out


def load_webb(path: Path = WEBB_CSV) -> Dict[str, float]:
    """6-digit SOC -> Webb (2020) exposure, if a prepared csv is present; else {} (gap)."""
    if not path.exists():
        return {}
    out: Dict[str, float] = {}
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                out[_soc6(row["soc6"])] = float(row["value"])
            except (KeyError, ValueError):
                continue
    return out


if __name__ == "__main__":
    print("AIOE occupations:", len(load_aioe()))
    print("EP projections:", len(load_ep_projections()))
    print("Webb occupations:", len(load_webb()))
