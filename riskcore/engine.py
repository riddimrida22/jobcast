"""The scoring engine. Turns a Profile plus a Snapshot and config weights into a
scored, sourced, decomposable assessment. Deterministic and I/O-free once constructed."""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any, List

from .model import Profile
from .snapshot import Snapshot
from . import countries

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = REPO_ROOT / "data" / "fixtures" / "snapshot.json"
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"
OVERLAY_DIR = REPO_ROOT / "data" / "overlays"


def _load_overlays(overlay_dir: Path = OVERLAY_DIR) -> Dict[str, Dict[str, Any]]:
    """Load any per-country wage overlays present on disk, keyed by country code.

    An overlay is data/overlays/<code>_wages.json with shape:
      {"source": "...", "snapshot": "...", "soc_median": {"<soc>": <median_in_local_currency>, ...}}
    Absent overlays are simply not loaded; the engine then withholds pay for that
    country rather than present US figures in the wrong currency.
    """
    out: Dict[str, Dict[str, Any]] = {}
    try:
        for f in (overlay_dir.glob("*_wages.json") if overlay_dir.exists() else []):
            code = f.name.split("_wages.json")[0].lower()
            if code in countries.COUNTRIES and code != countries.DEFAULT:
                with open(f, "r", encoding="utf-8") as fh:
                    out[code] = json.load(fh)
    except Exception:
        pass
    return out


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


# Function words and ultra-generic verbs that carry no skill signal, so overlap is driven by the
# meaningful nouns/verbs of the work (e.g. "records", "diagnose", "schedule", "weld").
_SKILL_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "their", "your", "you", "our",
    "are", "was", "were", "has", "have", "had", "will", "would", "can", "may", "into", "out",
    "off", "per", "via", "such", "other", "others", "all", "any", "new", "various", "including",
    "between", "within", "onto", "upon", "about", "over", "under", "using", "use", "used", "uses",
    "perform", "performed", "performing", "provide", "provided", "providing", "ensure", "ensuring",
    "maintain", "maintaining", "prepare", "preparing", "operate", "operating", "conduct", "assist",
    "work", "working", "tasks", "task", "related", "appropriate", "necessary", "according",
    "based", "well", "etc", "non", "one", "two", "each", "also", "them",
}


def _is_catch_all(occ: Dict[str, Any]) -> bool:
    """O*NET residual buckets ('... All Other', 'Miscellaneous ...') are not real target
    careers and usually carry no tasks, so they must never be offered as a green move."""
    title = (occ.get("title") or "").lower()
    return title.endswith("all other") or "all other" in title or title.startswith("miscellaneous")


def _skill_tokens(text: str) -> set:
    """Reduce a task statement or a self-reported skill to a set of meaningful lowercase stems,
    so two pieces of work can be compared for real overlap. Deterministic and data-only."""
    out = set()
    word = ""
    for ch in (text or "").lower():
        if ch.isalnum():
            word += ch
        else:
            if word:
                out.add(word)
            word = ""
    if word:
        out.add(word)
    stems = set()
    for w in out:
        if len(w) < 3 or w in _SKILL_STOP or w.isdigit():
            continue
        # Light singularisation so "records"/"record", "systems"/"system" match.
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 4 and w.endswith("es"):
            w = w[:-2]
        elif len(w) > 3 and w.endswith("s"):
            w = w[:-1]
        stems.add(w)
    return stems


class Engine:
    def __init__(self, snapshot: Snapshot, weights: Dict[str, Any],
                 sources: Dict[str, Any], tiers: Dict[str, Any],
                 overlays: Optional[Dict[str, Dict[str, Any]]] = None):
        self.snapshot = snapshot
        self.weights = weights
        self.sources = sources
        self.tiers = tiers
        # Per-country wage overlays (country code -> {soc_median, ...}). US needs none.
        self.overlays = _load_overlays() if overlays is None else overlays
        self._task_name_cache: Dict[str, List[str]] = {}   # soc -> core task names (green match)

    # ---- public API ------------------------------------------------------
    def assess(self, profile: Profile) -> Dict[str, Any]:
        occ = self.snapshot.match_title(profile.title)
        if occ is None:
            return {
                "ok": False,
                "error": "occupation_not_found",
                "message": "That job title is not in the current data snapshot.",
                "query": profile.title,
                "suggestions": self.snapshot.suggest_titles(profile.title, limit=5),
            }

        country = countries.resolve(profile.country)
        # US uses zip->metro geography; other countries are national-only for now.
        metro_id = self.snapshot.metro_for_zip(profile.zip_code) if country == countries.DEFAULT else None
        axes, decomposition = self._score_axes(occ, profile)
        # v2: the headline is the calibrated multi-factor blend (config exposure_model), not an
        # unfitted max(ai, robo). ai/robo come in seniority-adjusted via the axes; the task-
        # structure factors (routine, interpersonal) come from the occupation.
        base_exposure = self.combined_exposure(
            occ, ai100=axes["ai_software"], robo100=axes["physical_robotics"])
        timeline = self._timeline(occ, metro_id, base_exposure, profile)
        wages = self._wages(occ, metro_id, profile, country)
        adjacency = self._adjacency(occ, base_exposure)
        confidence = self._confidence_band(axes)
        drivers = self._key_drivers(occ, axes, decomposition, timeline, wages, profile)
        strategies = self._strategies(occ, axes, base_exposure, timeline, wages, adjacency,
                                      decomposition, profile)

        return {
            "ok": True,
            "occupation": {"soc": occ["soc"], "title": occ["title"],
                           "title_local": self._local_title(occ, country),
                           "job_zone": occ.get("job_zone"),
                           "family": self.snapshot.family_name(self.snapshot.family_code(occ["soc"]))},
            "location": {"metro_id": metro_id,
                         "metro": self.snapshot.metro_name(metro_id) if metro_id
                         else countries.info(country)["name"]},
            "country": country,
            "currency": countries.currency(country),
            "exposure": axes,
            "exposure_range": confidence,
            "base_exposure": round(base_exposure, 1),
            "key_drivers": drivers,
            "strategies": strategies,
            "timeline": timeline,
            "tasks": decomposition,
            "wages": wages,
            "adjacent_lower_risk": adjacency,
            "geo": self._geo_compare(occ),
            "sources": self.snapshot.data.get("sources") or self.sources.get("sources", []),
            "snapshot": {"id": self.snapshot.snapshot_id, "date": self.snapshot.snapshot_date,
                         "licensed": self.snapshot.licensed},
            "development_notice": None if self.snapshot.licensed
                else self.snapshot.data.get("development_notice"),
        }

    def what_if(self, profile: Profile, overrides: Dict[str, Any]) -> Dict[str, Any]:
        """Re-score with some inputs changed and report the deltas vs the baseline."""
        baseline = self.assess(profile)
        scenario_profile = profile.with_overrides(overrides)
        scenario = self.assess(scenario_profile)
        result = {"ok": baseline.get("ok") and scenario.get("ok"),
                  "overrides": overrides,
                  "baseline": baseline, "scenario": scenario}
        if result["ok"]:
            result["deltas"] = {
                "ai_software": round(scenario["exposure"]["ai_software"]
                                     - baseline["exposure"]["ai_software"], 1),
                "physical_robotics": round(scenario["exposure"]["physical_robotics"]
                                           - baseline["exposure"]["physical_robotics"], 1),
                "timeline_band_from": baseline["timeline"]["band"]["id"],
                "timeline_band_to": scenario["timeline"]["band"]["id"],
            }
        return result

    def mitigation_plan(self, profile: Profile, tier_id: str) -> Dict[str, Any]:
        """Tiered advice. The number of options is set by the tier. In v1 the options
        are derived deterministically from the adjacency data; production expands each
        with language-model-written detail (explain, never score)."""
        tier = next((t for t in self.tiers["tiers"] if t["id"] == tier_id), None)
        if tier is None:
            return {"ok": False, "error": "unknown_tier", "tier": tier_id}
        n = int(tier.get("mitigation_options", 0))
        assessment = self.assess(profile)
        if not assessment.get("ok"):
            return {"ok": False, "error": "occupation_not_found"}
        options = []
        for adj in assessment["adjacent_lower_risk"][:n]:
            options.append({
                "move_to": {"soc": adj["soc"], "title": adj["title"]},
                "why": (f"Lower combined exposure ({adj['max_exposure']} vs "
                        f"{assessment['base_exposure']}) and skill-adjacent to your current role."),
                "detail": "Production fills this with a language-model-written, data-grounded plan.",
            })
        return {"ok": True, "tier": tier_id, "options_count": n, "options": options,
                "note": "Options derived from adjacency data; advice is explanatory, not a score."}

    def future_careers(self, family: Optional[str] = None, max_zone: Optional[int] = None,
                       priority: str = "balanced", n: int = 15) -> List[Dict[str, Any]]:
        """Rank occupations by future fit for someone choosing a career: low automation
        exposure, good pay, and a positive real-wage trend, within an optional field and
        an education ceiling (O*NET job zone). Transparent, data-only ranking."""
        edu = {1: "Minimal prep", 2: "High school", 3: "Some college or training",
               4: "Bachelor's degree", 5: "Graduate degree"}
        # These are "careers worth aiming for" lists on a page about AI resilience, so a job
        # more exposed than this never belongs on them, however fast it is growing.
        SAFE_FLOOR = 50
        out = []
        for o in self.snapshot.all_occupations():
            wage = o.get("median_wage_national")
            if wage is None:
                continue
            soc = o["soc"]
            if family and self.snapshot.family_code(soc) != family:
                continue
            zone = o.get("job_zone")
            # When a schooling ceiling is set, drop anything above it AND anything whose
            # required schooling we can't confirm (zone missing) - otherwise catch-all
            # occupations with no job zone slip past the filter.
            if max_zone and (zone is None or zone > max_zone):
                continue
            base = self.combined_exposure(o)          # v2 calibrated blend, not max(ai, robo)
            safe = 100 - base
            if safe < SAFE_FLOOR:
                continue
            growth = o.get("projection_pct")              # BLS 2020-2030 projected % change
            if growth is None:
                growth = o.get("wage_trend_5yr_real_pct") or 0
            # Growth only tilts the ranking; it never leads it. Some occupations show huge
            # projected growth off a depressed 2020 base (e.g. pandemic-hit roles), so clamp
            # to a sane band and normalise to 0..100 before weighting. The card still shows
            # the real, unclamped figure.
            g = max(-20.0, min(15.0, growth))
            gnorm = (g + 20.0) / 35.0 * 100.0             # 0..100 within the clamped band
            paynorm = min(wage, 200000) / 2000.0          # 0..100
            ff = self.weights.get("future_fit", {})
            w = ff.get(priority if priority in ("safe", "pay") else "balanced",
                       {"safe": 0.50, "pay": 0.30, "growth": 0.20})
            fit = safe * w["safe"] + paynorm * w["pay"] + gnorm * w["growth"]
            out.append({"soc": soc, "title": o["title"], "base_exposure": round(base),
                        "resilience": round(safe), "median_wage": wage, "job_zone": zone,
                        "edu": edu.get(zone, "Varies"), "growth": round(growth, 1), "fit": round(fit, 1),
                        "family": self.snapshot.family_name(self.snapshot.family_code(soc))})
        # Order each list by the dimension its label promises, so the headline number
        # reads in order; the blended fit only drives the all-round view. The resilience
        # floor and fit still decide which jobs qualify.
        if priority == "pay":
            out.sort(key=lambda x: (-x["median_wage"], -x["resilience"]))
        elif priority == "safe":
            out.sort(key=lambda x: (-x["resilience"], -x["median_wage"]))
        else:
            out.sort(key=lambda x: -x["fit"])
        return out[:n]

    # ---- green option: a safer, reachable career from the person's skills ----
    def green_option(self, profile: Profile, user_skills: Optional[List[str]] = None,
                     n: int = 3) -> Dict[str, Any]:
        """The paid payoff: safer occupations this person can realistically move into using
        skills they already have. Fully data-driven and the one AI-free path - matches come
        from O*NET adjacency and core-task overlap crossed with the engine's own automation
        scores; the language model may later explain a target, but never invents the match or
        the numbers.

        Ranking is (how much safer) x (how reachable), where reachable = skill overlap between
        the person's skills and the target's O*NET core tasks, lifted by O*NET relatedness and
        an education (job-zone) fit. Returns {ok, your_exposure, targets:[...]}.
        """
        base = self.assess(profile)
        if not base.get("ok"):
            return {"ok": False, "error": "occupation_not_found"}
        occ = self.snapshot.match_title(profile.title)
        your_exposure = base["base_exposure"]
        your_soc = occ["soc"]
        your_zone = occ.get("job_zone")
        your_family = self.snapshot.family_code(your_soc)

        # The person's skill vocabulary: the real work they already do (their occupation's core
        # tasks) plus anything they ticked or typed. Both are O*NET-grounded or self-reported -
        # never model-generated.
        skill_tokens = set()
        for tk in occ.get("tasks", []):
            skill_tokens |= _skill_tokens(tk.get("name", ""))
        for s in (user_skills or []):
            skill_tokens |= _skill_tokens(s)
        has_user_skills = bool([s for s in (user_skills or []) if (s or "").strip()])

        # Candidate pool, kept to roles whose reachability is defensible from data - never a
        # cross-field leap invented from coincidental word overlap:
        #   1. O*NET related occupations (the authoritative transferable-skills signal), and
        #   2. same-field (SOC major group) roles within educational reach,
        # both only when they are meaningfully safer. The task overlap below then ranks them and
        # names which skills already carry and which to add. Residual "All Other" catch-all
        # occupations are excluded: they carry no task basis and are not real target careers.
        # A "clearly safer" move is a 6-point drop (meaningfully safer on the 0-100 scale). A
        # 2-to-6-point drop is a softer, still-real fallback - a closely related role at somewhat
        # lower risk - surfaced only when no clearly safer move exists, so the paid payoff still
        # names a reachable, honest option instead of falsely claiming the person is already safe.
        GREEN_MARGIN = 6
        SOFT_MARGIN = 2
        candidates: Dict[str, Dict[str, Any]] = {}
        adjacent_socs = set()
        for adj in occ.get("adjacent", []):
            full = self.snapshot.occupation(adj["soc"])
            # Use the full occupation when the snapshot carries it (richer: tasks, wage, zone);
            # otherwise fall back to the O*NET adjacency entry's own scores so the related role
            # is still offered. Either way the data is O*NET-derived, never invented.
            cand = full or {"soc": adj["soc"], "title": adj.get("title", ""),
                            "ai": adj.get("ai"), "robo": adj.get("robo"),
                            "interpersonal": adj.get("interpersonal"),
                            "routine_structured": adj.get("routine_structured"),
                            "tasks": [], "job_zone": None, "median_wage_national": None}
            if _is_catch_all(cand):
                continue
            candidates[adj["soc"]] = cand
            adjacent_socs.add(adj["soc"])
        for cand in self.snapshot.all_occupations():
            soc = cand["soc"]
            if soc == your_soc or soc in candidates or _is_catch_all(cand):
                continue
            if self.snapshot.family_code(soc) != your_family:
                continue                            # same field only for the wider pool
            cz = cand.get("job_zone")
            if your_zone is not None and cz is not None and cz > your_zone + 1:
                continue                            # out of educational reach
            if self._max_exposure(cand) <= your_exposure - SOFT_MARGIN:
                candidates[soc] = cand

        targets = []
        for soc, cand in candidates.items():
            cand_exp = self._max_exposure(cand)
            risk_drop = round(your_exposure - cand_exp, 1)
            if risk_drop < SOFT_MARGIN:             # must be at least somewhat safer
                continue
            is_adjacent = soc in adjacent_socs
            covered, to_add = [], []
            for name in self._occ_task_names(cand):
                toks = _skill_tokens(name)
                if not toks:
                    continue
                shared = toks & skill_tokens
                if len(shared) >= 2 or (toks and len(shared) / len(toks) >= 0.4):
                    covered.append(name)
                else:
                    to_add.append(name)
            m = len(covered) + len(to_add)
            qualified = (len(covered) / m) if m else (0.5 if is_adjacent else 0.3)
            # Reachability gate: O*NET-related roles always qualify (the relatedness IS the skill
            # signal). A same-field role that is not O*NET-related must still show real overlap -
            # at least two of its core tasks the person can already do - to count as reachable.
            if not is_adjacent and len(covered) < 2:
                continue
            zone_fit = (your_zone is None or cand.get("job_zone") is None
                        or cand.get("job_zone") <= your_zone)
            reach = 1.0
            if is_adjacent:
                reach *= 1.35
            if zone_fit:
                reach *= 1.1
            if your_zone is not None and cand.get("job_zone") is not None \
                    and cand.get("job_zone") > your_zone + 1:
                reach *= 0.6
            # Reachability leads the ranking (0.15 floor so a large drop still counts), so the
            # safest job the person can mostly already do wins over a safer one they cannot.
            # A durability tilt then favours destinations whose safety is human-centred (high
            # interpersonal, low routine) - the two backtest-validated factors - so the paid
            # payoff points people toward resilient work, not just a slightly lower number.
            score = risk_drop * (0.15 + 0.85 * qualified) * reach * self._durability(cand)
            targets.append({
                "soc": soc,
                "title": cand["title"],
                "max_exposure": round(cand_exp, 1),
                "your_exposure": your_exposure,
                "risk_drop": risk_drop,
                "qualified_pct": round(qualified * 100),
                "qualified_k": len(covered),
                "qualified_m": m,
                "have_skills": [self._short_task(x) for x in covered[:6]],
                "add_skills": [self._short_task(x) for x in to_add[:4]],
                "median_wage": cand.get("median_wage_national"),
                "job_zone": cand.get("job_zone"),
                "adjacent": is_adjacent,
                "growth": cand.get("projection_pct"),
                "soft": risk_drop < GREEN_MARGIN,
                "_score": round(score, 2),
            })

        # Lead with clearly-safer ("green") moves; only fall back to softer, still-real options
        # when there are none, so a strong result is never buried under a marginal one. When
        # nothing qualifies at all, callers use already_low to tell "already low-risk" apart from
        # "no reachable safer move in this field" - never a false "you're already safe".
        green = [t for t in targets if not t["soft"]]
        soft = [t for t in targets if t["soft"]]
        green.sort(key=lambda t: t["_score"], reverse=True)
        soft.sort(key=lambda t: t["_score"], reverse=True)
        chosen = green[:max(1, n)] if green else soft[:2]
        # The person's most AI-resistant work - their human edge - so the client can prove it when
        # the role is already safe ("ahead of the curve") instead of showing a bare empty state.
        resilient = sorted(base.get("tasks", []), key=lambda d: d.get("max", 0))
        resilient_tasks = [self._short_task(t["name"]) for t in resilient
                           if t.get("max", 100) < 45][:3]
        # Where this role sits versus every job we score (a simple, true "safer than X%" line).
        all_exp = [self._max_exposure(o) for o in self.snapshot.all_occupations()]
        safer_than_pct = (round(100 * sum(1 for e in all_exp if e > your_exposure) / len(all_exp))
                          if all_exp else None)
        return {"ok": True, "your_exposure": your_exposure,
                "occupation": occ["title"], "soc": your_soc,
                "used_user_skills": has_user_skills,
                "has_green": bool(green),
                "soft_only": (not green) and bool(soft),
                "already_low": your_exposure < 35,
                "resilient_tasks": resilient_tasks,
                "safer_than_pct": safer_than_pct,
                "targets": chosen}

    # ---- v2 calibrated exposure blend ------------------------------------
    def combined_exposure(self, occ: Dict[str, Any],
                          ai100: Optional[float] = None, robo100: Optional[float] = None) -> float:
        """The headline automation-exposure score (0-100) for an occupation, the calibrated v2
        blend defined in config/weights.json ("exposure_model"): a transparent weighted average
        of four task-intrinsic sub-scores, every term oriented so higher = more automatable
        (interpersonal enters as protection, 100 - interpersonal). The weights are set by the
        cross-validated backtest (analysis/calibrate.py, CALIBRATION.md); nothing here fits a
        model or calls a language model.

        ai100/robo100 let the caller pass already-adjusted axis scores (e.g. seniority-scaled);
        otherwise they come from the occupation's own ai/robo (occupation-level, else task mean).
        If the config has no exposure_model, or the occupation lacks the task-structure factors,
        we fall back to the v1 definition max(ai, robo) so the score never silently breaks.
        """
        if ai100 is None or robo100 is None:
            ai, robo = occ.get("ai"), occ.get("robo")
            if ai is None and robo is None:
                tasks = occ.get("tasks", [])
                if tasks:
                    ai = sum(t.get("ai", 0) for t in tasks) / len(tasks)
                    robo = sum(t.get("robo", 0) for t in tasks) / len(tasks)
            ai100 = (ai or 0.0) * 100 if ai100 is None else ai100
            robo100 = (robo or 0.0) * 100 if robo100 is None else robo100
        model = self.weights.get("exposure_model") or {}
        w = model.get("weights") if model.get("method") == "weighted_blend_0_100" else None
        routine, interp = occ.get("routine_structured"), occ.get("interpersonal")
        if not w or routine is None or interp is None:
            return _clamp(max(ai100, robo100))
        protection = 100.0 - interp * 100.0
        score = (w["ai"] * ai100 + w["robo"] * robo100
                 + w["routine_structured"] * routine * 100.0
                 + w["interpersonal_protection"] * protection)
        return _clamp(score)

    def _durability(self, cand: Dict[str, Any]) -> float:
        """Green-match tilt toward destinations whose safety is DURABLE: high interpersonal
        (strongest validated protector) and low routine_structured (strongest validated risk).
        Centred at 0.5 so an average role is neutral; bounded by config. 1.0 when the factors
        are absent (then combined_exposure already fell back to max(ai, robo))."""
        g = self.weights.get("green_match") or {}
        interp, routine = cand.get("interpersonal"), cand.get("routine_structured")
        if interp is None or routine is None or not g:
            return 1.0
        mult = (1.0 + g.get("interpersonal_bonus", 0.0) * (interp - 0.5)
                - g.get("routine_penalty", 0.0) * (routine - 0.5))
        return max(g.get("min_multiplier", 0.7), min(g.get("max_multiplier", 1.4), mult))

    def _occ_task_names(self, occ: Dict[str, Any]) -> List[str]:
        """Core-task statements for an occupation, cached by SOC (the green match scans the whole
        snapshot, so this keeps repeated requests cheap)."""
        soc = occ.get("soc") or ""
        hit = self._task_name_cache.get(soc)
        if hit is None:
            hit = [t.get("name", "") for t in (occ.get("tasks") or []) if t.get("name")]
            self._task_name_cache[soc] = hit
        return hit

    def _max_exposure(self, occ: Dict[str, Any]) -> float:
        """Combined automation exposure (0-100) for an occupation - the same calibrated v2 blend
        assess() reports as the headline, so adjacency and the green match compare like with like
        (a role is 'safer' only if its calibrated exposure is lower, not just its max(ai, robo))."""
        return self.combined_exposure(occ)

    # ---- scoring internals ----------------------------------------------
    def _score_axes(self, occ: Dict[str, Any], profile: Profile):
        # Headline axis scores use the calibrated occupation-level exposure (AI = Eloundou
        # beta over all tasks; robotics = O*NET work-context proxy), adjusted for seniority.
        # The fixture has no occupation-level fields, so fall back to the task mean there.
        factor = self._seniority_factor(profile)
        tasks = occ.get("tasks", [])
        if occ.get("ai") is not None or occ.get("robo") is not None:
            ai_raw, robo_raw = occ.get("ai") or 0.0, occ.get("robo") or 0.0
        elif tasks:
            ai_raw = sum(t["ai"] for t in tasks) / len(tasks)
            robo_raw = sum(t["robo"] for t in tasks) / len(tasks)
        else:
            ai_raw = robo_raw = 0.0
        ai_score = _clamp(ai_raw * 100 * factor)
        robo_score = _clamp(robo_raw * 100 * factor)
        # The task bars show per-task AI exposure (Eloundou task labels) vs the robotics proxy.
        decomposition = [
            {"id": t["id"], "name": t["name"],
             "ai": round(t["ai"] * 100, 1), "robo": round(t["robo"] * 100, 1),
             "max": round(max(t["ai"], t["robo"]) * 100, 1),
             "exposed": max(t["ai"], t["robo"]) >= 0.5}
            for t in occ.get("tasks", [])
        ]
        return {"ai_software": round(ai_score, 1),
                "physical_robotics": round(robo_score, 1)}, decomposition

    def _metro(self, occ, metro_id):
        """Metro {employment, median_wage, demand_trend} for this occupation: the
        fixture carries it on the occupation; the real snapshot keys it by SOC."""
        m = (occ.get("metros") or {}).get(metro_id)
        if m:
            return m
        return self.snapshot.metro_wage(occ.get("soc6") or occ.get("soc"), metro_id) or {}

    def _seniority_factor(self, profile: Profile) -> float:
        s = self.weights.get("seniority", {})
        years_full = s.get("years_for_full_shift", 20)
        max_red = s.get("max_exposure_reduction", 0.0)
        if profile.experience_years is None or years_full <= 0:
            return 1.0
        frac = min(profile.experience_years / years_full, 1.0)
        return 1.0 - (frac * max_red)

    def _timeline(self, occ, metro_id, base_exposure, profile: Profile):
        bands = self.weights["timeline_bands"]
        idx = len(bands) - 1
        for i, b in enumerate(bands):
            if base_exposure <= b["max_exposure"]:
                idx = i
                break
        trend = self._metro(occ, metro_id).get("demand_trend")
        if not trend:
            proj = occ.get("projection_pct")   # BLS national 2020-2030 projected % change
            if proj is not None:
                trend = "growing" if proj >= 10 else "declining" if proj <= 2 else "stable"
            else:
                trend = "stable"
        shift = self.weights.get("demand_trend_shift", {}).get(trend, 0)
        union_shift = 0
        if profile.union_status == "yes":
            union_shift = self.weights.get("union_protection", {}).get("yes_band_shift", 0)
        idx = max(0, min(len(bands) - 1, idx + shift + union_shift))
        band = bands[idx]

        remaining_years = None
        overlap = None
        if profile.age is not None:
            remaining_years = max(0, self.weights.get("retirement_age", 65) - profile.age)
            if band["id"] == "near_term_high" and remaining_years > 0:
                overlap = "This change is likely within my remaining working years."
            elif band["id"] == "largely_unaffected":
                overlap = "This role is unlikely to be automated within my working life."
            else:
                overlap = "Partial change is plausible within my working years; worth planning ahead."
        return {"band": {"id": band["id"], "label": band["label"]},
                "local_demand_trend": trend,
                "union_protected": profile.union_status == "yes",
                "union_note": ("Union coverage is factored in as negotiated protection that slows "
                               "displacement.") if profile.union_status == "yes" else None,
                "remaining_working_years": remaining_years,
                "overlap_note": overlap}

    def _local_title(self, occ, country: str):
        """A country-local occupation title (e.g. the Canadian-French NOC name), when the
        country overlay carries one for this occupation. Returned to the template, which
        shows it only in the matching UI language. None for US / when absent."""
        if country == countries.DEFAULT:
            return None
        titles = (self.overlays.get(country, {}) or {}).get("soc_title_fr", {})
        return titles.get(occ["soc"]) or titles.get(occ.get("soc6") or "") or None

    def _wages(self, occ, metro_id, profile: Profile, country: str = countries.DEFAULT):
        out: Dict[str, Any] = {"available": False}
        if country == countries.DEFAULT:
            median = self._metro(occ, metro_id).get("median_wage") \
                or occ.get("median_wage_national")
            trend = occ.get("wage_trend_5yr_real_pct")
        else:
            # Non-US: pay comes only from a country wage overlay keyed to the shared SOC.
            # No overlay entry -> withhold pay rather than present US dollars as local money.
            ov = self.overlays.get(country, {})
            soc_median = ov.get("soc_median", {})
            median = soc_median.get(occ["soc"]) or soc_median.get(occ.get("soc6") or "")
            trend = (ov.get("soc_trend", {}) or {}).get(occ["soc"])
        out["occupation_median_wage"] = median
        out["occupation_wage_trend_5yr_real_pct"] = trend

        if profile.pay_current is not None and median:
            out["pay_vs_median_pct"] = round((profile.pay_current / median - 1) * 100, 1)

        if profile.pay_current is not None and profile.pay_5yr_ago:
            base = self.snapshot.base_year
            ratio = self.snapshot.cpi_ratio(base - 5, base)
            out["nominal_change_pct"] = round(
                (profile.pay_current / profile.pay_5yr_ago - 1) * 100, 1)
            if ratio:
                real_past = profile.pay_5yr_ago * ratio
                out["real_change_pct"] = round(
                    (profile.pay_current / real_past - 1) * 100, 1)
                out["available"] = True
                occ_trend = trend
                if out["real_change_pct"] < 0:
                    out["signal"] = ("My pay has fallen in real terms over five years, "
                                     "an early sign of pressure on this role.")
                elif occ_trend is not None and out["real_change_pct"] < occ_trend:
                    out["signal"] = ("My real pay is rising but trailing my occupation, "
                                     "worth watching.")
                else:
                    out["signal"] = "My real pay is keeping pace with or beating my occupation."
        return out

    def _key_drivers(self, occ, axes, decomposition, timeline, wages, profile) -> List[Dict[str, Any]]:
        """The pyramid apex: rank the factors that actually move THIS person's result,
        most decisive first, each with a direction. Used on the result page, by what-if,
        and to target the paid mitigation plan."""
        drivers: List[Dict[str, Any]] = []

        # Top exposed tasks (drive the base score up).
        for t in sorted(decomposition, key=lambda d: max(d["ai"], d["robo"]), reverse=True)[:2]:
            axis = "AI/software" if t["ai"] >= t["robo"] else "physical/robotics"
            score = max(t["ai"], t["robo"])
            drivers.append({"factor": "task_exposure", "label": f"Task: {t['name']}",
                            "direction": "raises" if score >= 50 else "lowers",
                            "weight": score,
                            "detail": f"High {axis} exposure." if score >= 50
                                      else f"Resistant to {axis} automation."})

        # Local demand trend.
        trend = timeline.get("local_demand_trend", "stable")
        if trend == "declining":
            drivers.append({"factor": "local_demand", "label": "Local demand is declining",
                            "direction": "raises", "weight": 70,
                            "detail": "Falling demand for this role in my area pulls the timeline sooner."})
        elif trend == "growing":
            drivers.append({"factor": "local_demand", "label": "Local demand is growing",
                            "direction": "lowers", "weight": 40,
                            "detail": "Rising demand in your area pushes the timeline later."})

        # Wage trajectory and ROI-to-automate.
        if wages.get("available") and wages.get("real_change_pct") is not None \
                and wages["real_change_pct"] < 0:
            drivers.append({"factor": "wage_trajectory", "label": "My real pay is falling",
                            "direction": "raises", "weight": 55,
                            "detail": "Declining real wages are an early sign of pressure on the role."})
        if wages.get("pay_vs_median_pct") is not None and wages["pay_vs_median_pct"] > 20 \
                and max(axes.values()) >= 50:
            drivers.append({"factor": "automation_roi", "label": "Above-median pay in an exposed role",
                            "direction": "raises", "weight": 50,
                            "detail": "Higher pay raises the payoff from automating the role."})

        # Protective factors.
        if timeline.get("union_protected"):
            drivers.append({"factor": "union", "label": "Union coverage",
                            "direction": "lowers", "weight": 45,
                            "detail": "Negotiated protection slows involuntary displacement."})
        if profile.experience_years is not None and profile.experience_years >= 15:
            drivers.append({"factor": "seniority", "label": "Senior experience level",
                            "direction": "lowers", "weight": 35,
                            "detail": "Experience shifts my work toward less-exposed oversight tasks."})

        drivers.sort(key=lambda d: d["weight"], reverse=True)
        return drivers[:5]

    @staticmethod
    def _short_task(name: str) -> str:
        """O*NET task sentences run long; reduce one to its first clause (kept verbatim,
        so it can be quoted) for use inside advice text."""
        t = (name or "").split(",")[0].strip().rstrip(".")
        words = t.split()
        if len(words) > 12:
            t = " ".join(words[:12])
        return t

    def _strategies(self, occ, axes, base_exposure, timeline, wages, adjacency,
                    decomposition, profile) -> List[Dict[str, Any]]:
        """Concrete, data-grounded strategies to protect the person's livelihood, most
        relevant first. Grounded in THIS person's actual exposed tasks, adjacent roles, and
        skills so it reads specific, not generic. Deterministic; the paid plan rewrites each
        with a language-model version. Never changes the score."""
        s: List[Dict[str, Any]] = []
        band = timeline.get("band", {}).get("id")

        ranked = sorted(decomposition, key=lambda d: max(d["ai"], d["robo"]), reverse=True)
        top_exposed = ranked[0] if ranked else None
        safe = [d for d in decomposition if max(d["ai"], d["robo"]) < 45]
        top_safe = min(safe, key=lambda d: max(d["ai"], d["robo"])) if safe else None
        exp_q = ('“' + self._short_task(top_exposed["name"]) + '”') if top_exposed else None

        # 1. Timing, from the timeline band.
        if band == "near_term_high":
            s.append({"title": "Act within the next 1 to 2 years", "icon": "buffer",
                      "detail": "Displacement for this role is near-term. Start a concrete reskilling "
                                "plan now, while you still have income and leverage."})
        elif band == "partial_5_10yr":
            s.append({"title": "Use your 5 to 10 year runway", "icon": "buffer",
                      "detail": "Change here is gradual. Build resilient skills steadily and watch the "
                                "signals rather than waiting for a shock."})
        else:
            s.append({"title": "Stay sharp; urgency is low", "icon": "buffer",
                      "detail": "This role looks durable. Keep your skills current and watch for shifts "
                                "in your field."})

        # 2. The dominant threat axis, grounded in the person's own tasks.
        if axes["ai_software"] >= axes["physical_robotics"] and axes["ai_software"] >= 45:
            lead = (f"The most exposed part of your work is {exp_q} — exactly what today's AI does well. "
                    if exp_q else "The exposed parts of your work are routine and cognitive. ")
            edge = (f"Your edge is the human side, like “{self._short_task(top_safe['name'])}” and the "
                    "judgment around it; move more of your week there."
                    if top_safe else "Your edge is judgment, client relationships, and complex "
                    "problem-solving AI still cannot do; move more of your week there.")
            s.append({"title": "Lean into the human edge", "icon": "dna", "detail": lead + edge})
        elif axes["physical_robotics"] >= 45:
            lead = (f"Robotics targets the hands-on work, like {exp_q}. " if exp_q
                    else "Robotics targets the physical work. ")
            s.append({"title": "Move up from the task to the system", "icon": "pivot",
                      "detail": lead + "Shift toward supervising, maintaining, or programming the "
                      "automation instead of competing with it."})

        # 3. Get ahead by directing the tools, not racing them.
        if top_exposed and max(top_exposed["ai"], top_exposed["robo"]) >= 50:
            s.append({"title": "Direct the tools, don't race them", "icon": "automate",
                      "detail": f"Get hands-on with the AI tools arriving in your field and point them at "
                                f"your exposed work, like {exp_q}. Be the person who runs them, not the "
                                "one they replace."})

        # 4. A concrete lower-risk pivot.
        if adjacency:
            a = adjacency[0]
            s.append({"title": f"Pivot toward {a['title']}", "icon": "pivot",
                      "detail": f"It is skill-adjacent and less exposed ({a['max_exposure']} vs "
                                f"{round(base_exposure)}). A lateral move now beats a forced one later."})

        # 5. Financial resilience - the core of avoiding a livelihood shock.
        s.append({"title": "Build a financial buffer", "icon": "buffer",
                  "detail": "Keep 6 to 12 months of expenses and diversify your income, so a disruption "
                            "is a setback rather than a catastrophe."})

        # 6. Wage trajectory.
        if wages.get("available") and (wages.get("real_change_pct") or 0) < 0:
            s.append({"title": "Stop the income slide", "icon": "buffer",
                      "detail": "Your real pay is already falling. Renegotiate, add a credential, or move "
                                "before the erosion compounds."})

        # 7. Protection and credentials.
        if timeline.get("union_protected"):
            s.append({"title": "Use your collective leverage", "icon": "network",
                      "detail": "Union coverage can fund retraining and ease transitions. Push for those "
                                "protections while you have them."})
        else:
            s.append({"title": "Add a recognised credential", "icon": "credential",
                      "detail": "A certification or license raises the bar against automation and signals "
                                "value in a tightening market."})

        # 8. Skills the person listed.
        if profile.skills:
            adj_name = adjacency[0]["title"] if adjacency else "less-exposed roles"
            s.append({"title": "Market your transferable skills", "icon": "skill",
                      "detail": f"Your skills ({profile.skills}) carry into adjacent work like {adj_name}. "
                                "Frame them for where the work is heading, not just where it has been."})
        return s

    def _adjacency(self, occ, base_exposure) -> List[Dict[str, Any]]:
        out = []
        for adj in occ.get("adjacent", []):
            full = self.snapshot.occupation(adj["soc"])
            # Score the adjacent role on the same calibrated blend. Prefer the full occupation
            # (it carries the task-structure factors); fall back to the adjacency entry's own
            # ai/robo, where combined_exposure degrades to max(ai, robo).
            adj_exp = self.combined_exposure(full if full else adj)
            if adj_exp < base_exposure - 0.01:
                out.append({"soc": adj["soc"], "title": adj["title"],
                            "ai_software": round(adj["ai"] * 100, 1),
                            "physical_robotics": round(adj["robo"] * 100, 1),
                            "max_exposure": round(adj_exp, 1),
                            "projection_pct": (full or {}).get("projection_pct")})
        out.sort(key=lambda a: a["max_exposure"])
        return out

    @staticmethod
    def _soc_keys(occ) -> List[str]:
        """Candidate SOC keys, since sources key by 6-digit ('43-9021') or 8-digit
        ('43-9021.00') codes interchangeably."""
        soc = occ.get("soc") or ""
        soc6 = occ.get("soc6") or (soc.split(".")[0] if soc else "")
        cands = []
        for k in (soc, soc6, soc6 + ".00" if soc6 else "", soc + ".00" if "." not in soc else ""):
            if k and k not in cands:
                cands.append(k)
        return cands

    @classmethod
    def _soc_lookup(cls, mapping, occ):
        for k in cls._soc_keys(occ):
            if k in mapping:
                return mapping[k]
        return None

    @staticmethod
    def _state_of(metro_name: str):
        """Extract a 2-letter state from a 'City, ST' or 'City, ST1-ST2' metro name."""
        if not metro_name or "," not in metro_name:
            return None
        tail = metro_name.rsplit(",", 1)[1].strip()
        st = tail.split("-")[0].strip()[:2].upper()
        return st if len(st) == 2 and st.isalpha() else None

    def _geo_compare(self, occ) -> Dict[str, Any]:
        """Where this role pays most and where demand holds up. The exposure score does NOT
        vary by place (it is task-intrinsic); what varies is pay and local demand, so that is
        all this compares. Pay is each country's own median in its own currency, never
        converted. US detail is rolled up from metro data to states."""
        soc = occ["soc"]
        soc6 = occ.get("soc6") or soc[:7]
        out: Dict[str, Any] = {"countries": [], "states": [], "top_metros": [], "demand": None}

        # By country: US national + any country wage overlay keyed to the shared SOC.
        for code in ("us", "uk", "ca"):
            info = countries.info(code)
            cur = countries.currency(code)
            if code == "us":
                med = occ.get("median_wage_national")
            else:
                sm = (self.overlays.get(code, {}) or {}).get("soc_median", {})
                med = self._soc_lookup(sm, occ)
            if med:
                out["countries"].append({"code": code, "name": info["name"],
                                         "symbol": cur["symbol"], "median": round(med),
                                         "period": cur["period"]})

        # US metros -> state rollup (employment-weighted mean pay) + demand mix.
        mw = self._soc_lookup(self.snapshot.data.get("metro_wages", {}), occ) or {}
        metros, states = [], {}
        g = sdemand = d = 0
        for mid, m in mw.items():
            wage = m.get("median_wage")
            if not wage:
                continue
            emp = m.get("employment") or 0
            tr = m.get("demand_trend") or "stable"
            name = self.snapshot.metro_name(mid)
            st = self._state_of(name)
            metros.append({"name": name, "state": st, "median": round(wage), "demand": tr})
            if tr == "growing":
                g += 1
            elif tr == "declining":
                d += 1
            else:
                sdemand += 1
            if st:
                row = states.setdefault(st, {"w": 0.0, "e": 0.0, "g": 0, "d": 0})
                weight = emp or 1
                row["w"] += wage * weight
                row["e"] += weight
                row["g"] += 1 if tr == "growing" else 0
                row["d"] += 1 if tr == "declining" else 0

        strows = []
        for st, r in states.items():
            if r["e"] <= 0:
                continue
            strows.append({"state": st, "pay": round(r["w"] / r["e"]),
                           "trend": "growing" if r["g"] > r["d"]
                           else ("declining" if r["d"] > r["g"] else "mixed")})
        strows.sort(key=lambda r: r["pay"], reverse=True)
        out["states"] = strows
        out["top_metros"] = sorted(metros, key=lambda m: m["median"], reverse=True)[:6]
        if mw:
            out["demand"] = {"growing": g, "stable": sdemand, "declining": d,
                             "total": g + sdemand + d}
        return out

    def _confidence_band(self, axes) -> Dict[str, Any]:
        c = self.weights.get("confidence", {})
        hw = c.get("licensed_half_width") if self.snapshot.licensed \
            else c.get("fixture_half_width", 15)
        band = {}
        for k, v in axes.items():
            band[k] = [round(_clamp(v - hw), 1), round(_clamp(v + hw), 1)]
        band["half_width"] = hw
        return band


def load_default_engine() -> Engine:
    snapshot_path = os.environ.get("JOBCAST_SNAPSHOT") or str(DEFAULT_SNAPSHOT)
    snapshot = Snapshot.from_file(snapshot_path)
    # Curated colloquial job names -> real occupation, so the career search recognises them.
    extra_aliases = REPO_ROOT / "data" / "aliases_extra.json"
    if extra_aliases.exists():
        try:
            with open(extra_aliases, "r", encoding="utf-8") as fh:
                overlay = {k: v for k, v in json.load(fh).items() if not k.startswith("_")}
            snapshot.add_aliases(overlay)
        except (OSError, ValueError):
            pass
    def _load(name):
        with open(DEFAULT_CONFIG_DIR / name, "r", encoding="utf-8") as fh:
            return json.load(fh)
    engine = Engine(snapshot, _load("weights.json"), _load("sources.json"), _load("tiers.json"))
    cal_path = DEFAULT_CONFIG_DIR / "calibration.json"
    engine.calibration = _load("calibration.json") if cal_path.exists() else None
    return engine
