"""Per-occupation AI/software and physical/robotics exposure, from real data.

- AI / software axis: Eloundou et al. (2023) occupation exposure, measure beta = E1 + 0.5*E2
  (the paper's headline), from the human annotators (falls back to the GPT-4 rating).
  Keyed by O*NET-SOC; occupations with no direct row fall back to their SOC-group mean.
- Physical / robotics axis: a transparent proxy built from O*NET Work Context physical and
  manual variables (handling objects, standing, walking, repetitive motion, climbing,
  hazardous equipment, protective gear, machine-paced work), each on O*NET's 1-5 context
  scale, normalised and averaged. This measures physical/manual intensity, the part of a
  job a robot would have to do; it is improvable later with a dedicated robot-exposure
  dataset (e.g. Webb 2020). No language model sets either number.

Both are occupation-level; each task inherits its occupation's exposure for display and
aggregation. Documented limitation until task-level exposure is wired.
"""

import csv
import zipfile
from pathlib import Path
from typing import Dict, Any

ROOT = Path(__file__).resolve().parents[1]
ELOUNDOU_CSV = ROOT / "data" / "cache" / "eloundou_occ_level.csv"
ONET_ZIP = ROOT / "data" / "cache" / "onet_db_29_1_text.zip"

# O*NET Work Context physical/manual elements (CX scale 1-5) used for the robotics proxy.
PHYS_ELEMENTS = {
    "4.C.2.d.1.g": "Using hands to handle, control, or feel objects",
    "4.C.2.d.1.b": "Spend time standing",
    "4.C.2.d.1.d": "Spend time walking and running",
    "4.C.2.d.1.i": "Spend time making repetitive motions",
    "4.C.2.d.1.c": "Spend time climbing",
    "4.C.2.d.1.e": "Spend time kneeling, crouching, stooping, crawling",
    "4.C.2.d.1.h": "Spend time bending or twisting the body",
    "4.C.2.c.1.e": "Exposed to hazardous equipment",
    "4.C.2.e.1.d": "Wear common protective or safety equipment",
    "4.C.3.d.3": "Pace determined by speed of equipment",
}


def load_ai(csv_path: Path = ELOUNDOU_CSV) -> Dict[str, float]:
    """O*NET-SOC -> AI exposure (0..1), human beta preferred, GPT-4 beta as fallback."""
    out: Dict[str, float] = {}
    with open(csv_path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            val = row.get("human_rating_beta") or row.get("dv_rating_beta")
            try:
                out[row["O*NET-SOC Code"]] = float(val)
            except (TypeError, ValueError):
                continue
    return out


def load_robo(zip_path: Path = ONET_ZIP) -> Dict[str, float]:
    """O*NET-SOC -> robotics proxy (0..1) from averaged physical work-context scores."""
    with zipfile.ZipFile(zip_path) as zf:
        raw = zf.read("db_29_1_text/Work Context.txt").decode("utf-8", "replace").splitlines()
    hdr = raw[0].split("\t")
    i = {h: n for n, h in enumerate(hdr)}
    acc: Dict[str, list] = {}
    for line in raw[1:]:
        c = line.split("\t")
        if c[i["Scale ID"]] != "CX" or c[i["Element ID"]] not in PHYS_ELEMENTS:
            continue
        try:
            v = float(c[i["Data Value"]])
        except ValueError:
            continue
        acc.setdefault(c[i["O*NET-SOC Code"]], []).append((v - 1.0) / 4.0)  # 1..5 -> 0..1
    return {k: round(sum(vs) / len(vs), 4) for k, vs in acc.items() if vs}


def _soc_group_mean(ai: Dict[str, float]) -> Dict[str, float]:
    groups: Dict[str, list] = {}
    for code, v in ai.items():
        groups.setdefault(code.split("-")[0], []).append(v)
    return {g: sum(vs) / len(vs) for g, vs in groups.items()}


def attach_exposure(occupations: Dict[str, Dict[str, Any]],
                    zip_path: Path = ONET_ZIP, csv_path: Path = ELOUNDOU_CSV) -> Dict[str, int]:
    """Fill each occupation's and task's 'ai' and 'robo' (0..1) in place.
    Returns coverage counts."""
    ai = load_ai(csv_path)
    robo = load_robo(zip_path)
    group_mean = _soc_group_mean(ai)
    overall = sum(ai.values()) / len(ai) if ai else 0.0
    stats = {"ai_direct": 0, "ai_fallback": 0, "robo_direct": 0, "robo_missing": 0}

    for code, occ in occupations.items():
        if code in ai:
            a = ai[code]; stats["ai_direct"] += 1
        else:
            a = group_mean.get(code.split("-")[0], overall); stats["ai_fallback"] += 1
        if code in robo:
            r = robo[code]; stats["robo_direct"] += 1
        else:
            r = 0.0; stats["robo_missing"] += 1
        occ["ai"] = round(a, 4)
        occ["robo"] = round(r, 4)
        for t in occ.get("tasks", []):
            t["ai"] = occ["ai"]
            t["robo"] = occ["robo"]
    return stats
