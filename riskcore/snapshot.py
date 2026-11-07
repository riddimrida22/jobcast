"""Load and query a data snapshot. A snapshot is a dated, immutable bundle of source
data (O*NET tasks, BLS wages and demand, CPI). v1 ships a development fixture; production
replaces the file with a pulled, versioned snapshot of the same shape."""

import json
from pathlib import Path
from typing import Optional, Dict, Any, List


class Snapshot:
    def __init__(self, data: Dict[str, Any]):
        self.data = data
        self.snapshot_id = data.get("snapshot_id", "unknown")
        self.snapshot_date = data.get("snapshot_date", "unknown")
        self.licensed = bool(data.get("licensed", False))
        self.base_year = int(data.get("base_year"))
        self._occ_by_soc: Dict[str, Dict[str, Any]] = {}
        self._alias_index: List[tuple] = []  # (alias_lower, soc, is_primary)
        for occ in data.get("occupations", []):
            self._occ_by_soc[occ["soc"]] = occ
            self._alias_index.append((occ["title"].lower().strip(), occ["soc"], True))
            for name in occ.get("aliases", []):
                self._alias_index.append((name.lower().strip(), occ["soc"], False))

    # ---- loading ---------------------------------------------------------
    @classmethod
    def from_file(cls, path: str) -> "Snapshot":
        with open(path, "r", encoding="utf-8") as fh:
            return cls(json.load(fh))

    # ---- occupation lookup ----------------------------------------------
    def occupation(self, soc: str) -> Optional[Dict[str, Any]]:
        return self._occ_by_soc.get(soc)

    def all_occupations(self) -> List[Dict[str, Any]]:
        return list(self.data.get("occupations", []))

    # ---- families (the general field, SOC major group) ------------------
    def family_code(self, soc: str) -> str:
        return (soc or "").split("-")[0]

    def family_name(self, code: str) -> str:
        return self.data.get("families", {}).get(code, code)

    def families(self) -> List[Dict[str, str]]:
        """Families present in the snapshot, each with the jobs that roll up to it,
        sorted by family name then job title."""
        groups: Dict[str, List[Dict[str, str]]] = {}
        for occ in self.all_occupations():
            code = self.family_code(occ["soc"])
            groups.setdefault(code, []).append({"soc": occ["soc"], "title": occ["title"]})
        out = []
        for code in sorted(groups, key=lambda c: self.family_name(c)):
            jobs = sorted(groups[code], key=lambda j: j["title"])
            out.append({"code": code, "name": self.family_name(code), "jobs": jobs})
        return out

    def _score_match(self, alias: str, q: str, is_primary: bool) -> int:
        """Higher is better. Exact beats prefix beats whole-word-contains; primary titles
        and shorter names break ties. Returns 0 for no match."""
        if alias == q:
            base = 1000
        elif alias.startswith(q) or q.startswith(alias):
            base = 600
        elif f" {q} " in f" {alias} ":            # q is a whole word inside alias
            base = 300
        else:
            qw, aw = set(q.split()), set(alias.split())
            shared = qw & aw
            if not shared:
                return 0
            base = 120 + 30 * len(shared)         # token overlap fallback
        base += 150 if is_primary else 0          # primary titles beat alternate titles
        base -= min(len(alias), 60) // 4          # prefer shorter, more specific names
        return base

    def match_title(self, title: str) -> Optional[Dict[str, Any]]:
        """Map a free-text job title to the best-matching occupation, or None."""
        if not title:
            return None
        q = title.lower().strip()
        best_soc, best_score = None, 0
        for alias, soc, is_primary in self._alias_index:
            s = self._score_match(alias, q, is_primary)
            if s > best_score:
                best_soc, best_score = soc, s
        return self._occ_by_soc[best_soc] if best_soc else None

    def suggest_titles(self, prefix: str, limit: int = 10) -> List[Dict[str, str]]:
        """Autocomplete: occupations whose title or alias matches, best first."""
        q = (prefix or "").lower().strip()
        if not q:
            return []
        scored: Dict[str, int] = {}
        for alias, soc, is_primary in self._alias_index:
            s = self._score_match(alias, q, is_primary)
            if s <= 0 and q in alias:
                s = 100 - min(len(alias), 60) // 4     # loose contains, ranked low
            if s > scored.get(soc, 0):
                scored[soc] = s
        ranked = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        return [{"soc": soc, "title": self._occ_by_soc[soc]["title"]} for soc, _ in ranked]

    # ---- metro / geography ----------------------------------------------
    def metro_for_zip(self, value: Optional[str]) -> str:
        """Back-compat name; accepts a ZIP or a 'City, ST' string."""
        return self.metro_for_location(value)

    def metro_for_location(self, value: Optional[str]) -> str:
        """Resolve a metro from either a 5-digit ZIP or a 'City, ST' / 'City ST' string.
        Falls back to the national row when nothing matches."""
        xwalk = self.data.get("zip_to_metro", {})
        default = xwalk.get("default", "US")
        if not value:
            return default
        s = str(value).strip()
        if not s:
            return default
        # ZIP code: 5 digits
        digits = "".join(ch for ch in s if ch.isdigit())
        if s.replace("-", "").isdigit() and len(digits) >= 5:
            return xwalk.get("map", {}).get(digits[:5], default)
        # "City, ST" or "City ST": trailing 2-letter state + a city
        parts = s.replace(",", " ").split()
        if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1].isalpha():
            state = parts[-1].upper()
            city = " ".join(parts[:-1]).strip().lower()
            fallback = None
            for code, name in self.data.get("metros", {}).items():
                if code == "US" or "," not in name:
                    continue
                cities, _, states = name.rpartition(",")
                st_tokens = [t.strip().upper() for t in states.strip().split("-")]
                if state not in st_tokens:
                    continue
                cl = cities.lower()
                if city and city in cl:
                    first = cl.split("-")[0].strip()
                    if first.startswith(city) or city.startswith(first):
                        return code
                    fallback = fallback or code
            if fallback:
                return fallback
        return default

    def metro_name(self, metro_id: str) -> str:
        return self.data.get("metros", {}).get(metro_id, metro_id)

    def metro_wage(self, soc6: str, metro_id: str) -> Optional[Dict[str, Any]]:
        """Metro-level {employment, median_wage, demand_trend} for a SOC, or None."""
        return self.data.get("metro_wages", {}).get(soc6, {}).get(metro_id)

    def metros_list(self) -> List[Dict[str, str]]:
        """Metros (excluding the national row), sorted by name, for the location picker."""
        out = [{"code": c, "name": n} for c, n in self.data.get("metros", {}).items() if c != "US"]
        return sorted(out, key=lambda m: m["name"])

    # ---- cpi -------------------------------------------------------------
    def cpi_ratio(self, from_year: int, to_year: int) -> Optional[float]:
        index = self.data.get("cpi", {}).get("index", {})
        a = index.get(str(from_year))
        b = index.get(str(to_year))
        if a is None or b is None or a == 0:
            return None
        return b / a
