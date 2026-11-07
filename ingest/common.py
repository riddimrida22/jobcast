"""Shared ingestion helpers: HTTP with caching, a download manifest, the BLS public
API client, and snapshot writing. Standard library only."""

import json
import time
import hashlib
import urllib.request
from pathlib import Path
from datetime import date
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "cache"
SNAPSHOT_DIR = ROOT / "data" / "snapshots"
USER_AGENT = "Jobcast-research/0.1 (occupation data ingestion)"

BLS_API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"


def _ensure_dirs():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def http_get(url: str, binary: bool = False, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return data if binary else data.decode("utf-8", errors="replace")


def download_to_cache(url: str, name: str, force: bool = False) -> Path:
    """Download a file to data/cache/<name> unless already present. Returns the path.
    Prints the size so a download is never silent."""
    _ensure_dirs()
    dest = CACHE_DIR / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        print(f"cached: {name} ({dest.stat().st_size} bytes)")
        return dest
    print(f"downloading {url} ...")
    data = http_get(url, binary=True)
    dest.write_bytes(data)
    print(f"saved: {name} ({len(data)} bytes)")
    _record_manifest(name, url, len(data))
    return dest


def _record_manifest(name: str, url: str, size: int):
    manifest = CACHE_DIR / "manifest.json"
    entries = {}
    if manifest.exists():
        entries = json.loads(manifest.read_text(encoding="utf-8"))
    entries[name] = {"url": url, "size": size,
                     "fetched": date.today().isoformat()}
    manifest.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def bls_series(series_ids: List[str], start_year: int, end_year: int,
               api_key: Optional[str] = None, annual_average: bool = True) -> Dict[str, Any]:
    """Fetch BLS series via the public API. Keyless allows up to 25 queries/day and 10
    years; a free key (env JOBCAST_BLS_KEY) allows 500/day and 20 years. Batches of up
    to 50 series per request (keyed) / 25 (keyless) are the caller's responsibility."""
    payload: Dict[str, Any] = {"seriesid": series_ids,
                               "startyear": str(start_year), "endyear": str(end_year),
                               "annualaverage": annual_average}
    if api_key:
        payload["registrationkey"] = api_key
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BLS_API, data=body,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    if out.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API: {out.get('status')} {out.get('message')}")
    return out


def bls_annual_values(series: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    """Reduce a BLS API response to {series_id: {year: annual_value}} using the annual
    average row (period M13) when present, else the latest monthly value that year."""
    result: Dict[str, Dict[str, float]] = {}
    for s in series["Results"]["series"]:
        by_year: Dict[str, float] = {}
        annual: Dict[str, float] = {}
        for row in s["data"]:
            try:
                val = float(row["value"])
            except ValueError:
                continue
            if row["period"] == "M13":
                annual[row["year"]] = val
            else:
                by_year.setdefault(row["year"], val)  # data is newest-first
        for year in set(list(annual) + list(by_year)):
            result.setdefault(s["seriesID"], {})[year] = annual.get(year, by_year.get(year))
    return result


def write_snapshot(data: Dict[str, Any], licensed: bool = True) -> Path:
    _ensure_dirs()
    today = date.today().isoformat()
    data.setdefault("snapshot_id", f"SNAPSHOT-{today}")
    data.setdefault("snapshot_date", today)
    data["licensed"] = licensed
    dest = SNAPSHOT_DIR / f"snapshot-{today}.json"
    dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"snapshot written: {dest} ({dest.stat().st_size} bytes, {len(data.get('occupations', []))} occupations)")
    return dest
