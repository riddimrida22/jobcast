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
TASK_LABELS = ROOT / "data" / "cache" / "exposure" / "task_labels.tsv"
_LABEL_TO_AI = {"T0": 0.0, "T1": 1.0, "T2": 0.5}   # E1 direct LLM exposure; E2 exposed only with extra tools (beta weights it 0.5)

# O*NET Work Context elements for the robotics proxy, grouped by how they relate to robot
# automatability (Frey & Osborne 2017 "engineering bottlenecks"). Structured, repetitive
# physical work is robot-friendly; the need for dexterity in cramped/awkward/variable
# positions is a bottleneck - which is why skilled trades, very physical but unstructured,
# are hard to automate. CX scale 1-5, normalised to 0-1.
PHYS_PRESENCE = {   # is this physical, on-your-feet work at all (vs desk work)?
    "4.C.2.d.1.b": "Spend time standing",
    "4.C.2.d.1.d": "Spend time walking and running",
}
PHYS_ROUTINE = {    # structured / repetitive / machine-paced work robots do well -> raises risk
    "4.C.2.d.1.i": "Spend time making repetitive motions",
    "4.C.3.d.3": "Pace determined by speed of equipment",
    "4.C.3.b.7": "Importance of repeating same tasks",
    "4.C.3.b.8": "Structured versus unstructured work",
}
PHYS_BOTTLENECK = {  # dexterity in awkward/variable positions robots do poorly -> lowers risk
    "4.C.2.b.1.e": "Cramped work space, awkward positions",
    "4.C.2.d.1.c": "Spend time climbing ladders, scaffolds, or poles",
    "4.C.2.d.1.e": "Spend time kneeling, crouching, stooping, or crawling",
    "4.C.2.d.1.h": "Spend time bending or twisting the body",
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
    """O*NET-SOC -> robotics proxy (0..1). Structured, repetitive physical work raises the
    score; the need for dexterity in cramped/awkward/variable positions (an automation
    bottleneck) lowers it - so skilled trades are not scored as if a robot could do them."""
    with zipfile.ZipFile(zip_path) as zf:
        raw = zf.read("db_29_1_text/Work Context.txt").decode("utf-8", "replace").splitlines()
    hdr = raw[0].split("\t")
    i = {h: n for n, h in enumerate(hdr)}
    wanted = set(PHYS_PRESENCE) | set(PHYS_ROUTINE) | set(PHYS_BOTTLENECK)
    vals: Dict[str, Dict[str, float]] = {}
    for line in raw[1:]:
        c = line.split("\t")
        if c[i["Scale ID"]] != "CX" or c[i["Element ID"]] not in wanted:
            continue
        try:
            v = (float(c[i["Data Value"]]) - 1.0) / 4.0   # 1..5 -> 0..1
        except ValueError:
            continue
        vals.setdefault(c[i["O*NET-SOC Code"]], {})[c[i["Element ID"]]] = v

    def _mean(d: Dict[str, float], els) -> float:
        xs = [d[e] for e in els if e in d]
        return sum(xs) / len(xs) if xs else 0.0

    out: Dict[str, float] = {}
    for soc, d in vals.items():
        presence = _mean(d, PHYS_PRESENCE)       # on-your-feet physical work
        routine = _mean(d, PHYS_ROUTINE)         # structured/repetitive -> robot-friendly
        bottleneck = _mean(d, PHYS_BOTTLENECK)   # dexterity in awkward positions -> robot-hostile
        r = (presence ** 0.5) * routine * (1 - 0.85 * bottleneck)
        out[soc] = round(max(0.0, min(1.0, r)), 4)
    return out


def load_task_ai(path: Path = TASK_LABELS) -> Dict[str, float]:
    """Task ID -> AI exposure (0..1) from Eloundou's per-task labels (human preferred)."""
    import csv
    out: Dict[str, float] = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            lbl = (row.get("human_automation") or row.get("gpt4_automation") or "").strip()
            if lbl in _LABEL_TO_AI:
                out[row["Task ID"].strip()] = _LABEL_TO_AI[lbl]
    return out


def _soc_group_mean(ai: Dict[str, float]) -> Dict[str, float]:
    groups: Dict[str, list] = {}
    for code, v in ai.items():
        groups.setdefault(code.split("-")[0], []).append(v)
    return {g: sum(vs) / len(vs) for g, vs in groups.items()}


def attach_exposure(occupations: Dict[str, Dict[str, Any]],
                    zip_path: Path = ONET_ZIP, csv_path: Path = ELOUNDOU_CSV) -> Dict[str, int]:
    """Fill each occupation's and task's 'ai' and 'robo' (0..1) in place.
    Returns coverage counts."""
    ai = load_ai(csv_path)              # occupation-level beta (fallback for unlabeled tasks)
    robo = load_robo(zip_path)
    task_ai = load_task_ai()            # per-task AI exposure
    group_mean = _soc_group_mean(ai)
    overall = sum(ai.values()) / len(ai) if ai else 0.0
    stats = {"ai_direct": 0, "ai_fallback": 0, "robo_direct": 0, "robo_missing": 0,
             "task_labeled": 0, "task_fallback": 0}

    for code, occ in occupations.items():
        if code in ai:
            beta = ai[code]; stats["ai_direct"] += 1
        else:
            beta = group_mean.get(code.split("-")[0], overall); stats["ai_fallback"] += 1
        if code in robo:
            r = robo[code]; stats["robo_direct"] += 1
        else:
            r = 0.0; stats["robo_missing"] += 1
        occ["robo"] = round(r, 4)
        tvals = []
        for t in occ.get("tasks", []):
            tid = str(t.get("id", "")).strip()
            if tid in task_ai:
                t_ai = task_ai[tid]; stats["task_labeled"] += 1
            else:
                t_ai = beta; stats["task_fallback"] += 1
            t["ai"] = round(t_ai, 4)
            t["robo"] = round(r, 4)
            tvals.append(t_ai)
        # Gauge uses the calibrated occupation-level beta (over all tasks); the per-task
        # labels above drive only the task-bar breakdown on the result page.
        occ["ai"] = round(beta, 4)
    return stats
