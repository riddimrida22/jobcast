"""Parse the O*NET text database zip into occupation skeletons: title, SOC, job zone,
tasks, and alternate-title aliases. Exposure scores (AI/robotics) are attached separately
by exposure.py; this module only provides the occupation and task structure."""

import io
import zipfile
from typing import Dict, Any, List

from . import sources
from .common import download_to_cache

MAX_TASKS = 8          # keep the most relevant core tasks per occupation
MAX_ALIASES = 15


def _read_table(zf: zipfile.ZipFile, suffix: str) -> List[Dict[str, str]]:
    name = next((n for n in zf.namelist() if n.endswith(suffix)), None)
    if name is None:
        raise FileNotFoundError(f"{suffix} not found in O*NET zip")
    raw = zf.read(name).decode("utf-8", errors="replace")
    lines = raw.splitlines()
    header = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = line.split("\t")
        rows.append({header[i]: (cells[i] if i < len(cells) else "") for i in range(len(header))})
    return rows


def soc6(onetsoc: str) -> str:
    """15-1252.00 -> 15-1252."""
    return onetsoc.split(".")[0]


def build_occupations(zip_path) -> Dict[str, Dict[str, Any]]:
    with zipfile.ZipFile(zip_path) as zf:
        occ_rows = _read_table(zf, "Occupation Data.txt")
        task_rows = _read_table(zf, "Task Statements.txt")
        zone_rows = _read_table(zf, "Job Zones.txt")
        alt_rows = _read_table(zf, "Alternate Titles.txt")

    zones = {r["O*NET-SOC Code"]: r.get("Job Zone") for r in zone_rows}
    aliases: Dict[str, List[str]] = {}
    for r in alt_rows:
        aliases.setdefault(r["O*NET-SOC Code"], [])
        title = r.get("Alternate Title", "").strip()
        if title and len(aliases[r["O*NET-SOC Code"]]) < MAX_ALIASES:
            aliases[r["O*NET-SOC Code"]].append(title)

    tasks: Dict[str, List[Dict[str, str]]] = {}
    for r in task_rows:
        if r.get("Task Type", "") == "Supplemental":   # keep Core and n/a, drop Supplemental
            continue
        key = r["O*NET-SOC Code"]
        tasks.setdefault(key, [])
        if len(tasks[key]) < MAX_TASKS:
            tasks[key].append({"id": r.get("Task ID", "").strip(),
                               "name": r.get("Task", "").strip()})

    occupations: Dict[str, Dict[str, Any]] = {}
    for r in occ_rows:
        code = r["O*NET-SOC Code"]
        occupations[code] = {
            "onetsoc": code,
            "soc": soc6(code),
            "title": r.get("Title", "").strip(),
            "job_zone": int(zones[code]) if zones.get(code, "").isdigit() else None,
            "aliases": aliases.get(code, []),
            "tasks": tasks.get(code, []),
        }
    return occupations


def build_related(zip_path, tiers=("Primary-Short", "Primary-Long"), max_related=6) -> Dict[str, List[str]]:
    """O*NET-SOC -> ordered list of related O*NET-SOC codes (closest first)."""
    with zipfile.ZipFile(zip_path) as zf:
        rows = _read_table(zf, "Related Occupations.txt")
    out: Dict[str, List[Dict[str, str]]] = {}
    for r in rows:
        if tiers and r.get("Relatedness Tier") not in tiers:
            continue
        key = r["O*NET-SOC Code"]
        out.setdefault(key, []).append({"code": r["Related O*NET-SOC Code"],
                                        "index": int(r.get("Index", "999") or 999)})
    return {k: [x["code"] for x in sorted(v, key=lambda d: d["index"])[:max_related]]
            for k, v in out.items()}


def cached_zip():
    return download_to_cache(sources.ONET["url"], sources.ONET["cache_name"])


def fetch_and_parse() -> Dict[str, Dict[str, Any]]:
    return build_occupations(cached_zip())


if __name__ == "__main__":
    occs = fetch_and_parse()
    print(f"parsed {len(occs)} O*NET occupations")
    sample = next(iter(occs.values()))
    print("sample:", sample["soc"], sample["title"], "tasks:", len(sample["tasks"]))
