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
        base_exposure = max(axes["ai_software"], axes["physical_robotics"])
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
            base = max(o.get("ai") or 0, o.get("robo") or 0) * 100
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
            if priority == "safe":
                fit = safe * 0.65 + paynorm * 0.20 + gnorm * 0.15
            elif priority == "pay":
                fit = safe * 0.30 + paynorm * 0.55 + gnorm * 0.15
            else:
                fit = safe * 0.50 + paynorm * 0.30 + gnorm * 0.20
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
            adj_max = max(adj["ai"], adj["robo"]) * 100
            if adj_max < base_exposure - 0.01:
                full = self.snapshot.occupation(adj["soc"]) or {}
                out.append({"soc": adj["soc"], "title": adj["title"],
                            "ai_software": round(adj["ai"] * 100, 1),
                            "physical_robotics": round(adj["robo"] * 100, 1),
                            "max_exposure": round(adj_max, 1),
                            "projection_pct": full.get("projection_pct")})
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
