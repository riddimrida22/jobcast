"""The scoring engine. Turns a Profile plus a Snapshot and config weights into a
scored, sourced, decomposable assessment. Deterministic and I/O-free once constructed."""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any, List

from .model import Profile
from .snapshot import Snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = REPO_ROOT / "data" / "fixtures" / "snapshot.json"
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


class Engine:
    def __init__(self, snapshot: Snapshot, weights: Dict[str, Any],
                 sources: Dict[str, Any], tiers: Dict[str, Any]):
        self.snapshot = snapshot
        self.weights = weights
        self.sources = sources
        self.tiers = tiers

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

        metro_id = self.snapshot.metro_for_zip(profile.zip_code)
        axes, decomposition = self._score_axes(occ, profile)
        base_exposure = max(axes["ai_software"], axes["physical_robotics"])
        timeline = self._timeline(occ, metro_id, base_exposure, profile)
        wages = self._wages(occ, metro_id, profile)
        adjacency = self._adjacency(occ, base_exposure)
        confidence = self._confidence_band(axes)
        drivers = self._key_drivers(occ, axes, decomposition, timeline, wages, profile)
        strategies = self._strategies(axes, base_exposure, timeline, wages, adjacency, profile)

        return {
            "ok": True,
            "occupation": {"soc": occ["soc"], "title": occ["title"],
                           "job_zone": occ.get("job_zone"),
                           "family": self.snapshot.family_name(self.snapshot.family_code(occ["soc"]))},
            "location": {"metro_id": metro_id, "metro": self.snapshot.metro_name(metro_id)},
            "exposure": axes,
            "exposure_range": confidence,
            "base_exposure": round(base_exposure, 1),
            "key_drivers": drivers,
            "strategies": strategies,
            "timeline": timeline,
            "tasks": decomposition,
            "wages": wages,
            "adjacent_lower_risk": adjacency,
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
        out = []
        for o in self.snapshot.all_occupations():
            wage = o.get("median_wage_national")
            if wage is None:
                continue
            soc = o["soc"]
            if family and self.snapshot.family_code(soc) != family:
                continue
            zone = o.get("job_zone")
            if max_zone and zone and zone > max_zone:
                continue
            base = max(o.get("ai") or 0, o.get("robo") or 0) * 100
            trend = o.get("wage_trend_5yr_real_pct") or 0
            safe = 100 - base
            paynorm = min(wage, 200000) / 2000.0          # 0..100
            if priority == "safe":
                fit = safe * 0.70 + paynorm * 0.20 + trend * 1.0
            elif priority == "pay":
                fit = safe * 0.30 + paynorm * 0.60 + trend * 1.0
            else:
                fit = safe * 0.50 + paynorm * 0.40 + trend * 1.2
            out.append({"soc": soc, "title": o["title"], "base_exposure": round(base),
                        "resilience": round(safe), "median_wage": wage, "job_zone": zone,
                        "edu": edu.get(zone, "Varies"), "trend": round(trend, 1), "fit": round(fit, 1),
                        "family": self.snapshot.family_name(self.snapshot.family_code(soc))})
        out.sort(key=lambda x: -x["fit"])
        return out[:n]

    # ---- scoring internals ----------------------------------------------
    def _score_axes(self, occ: Dict[str, Any], profile: Profile):
        tasks = occ.get("tasks", [])
        if not tasks:
            # Fall back to occupation-level exposure when task rows are absent.
            factor = self._seniority_factor(profile)
            ai = _clamp((occ.get("ai") or 0.0) * 100 * factor)
            robo = _clamp((occ.get("robo") or 0.0) * 100 * factor)
            return {"ai_software": round(ai, 1), "physical_robotics": round(robo, 1)}, []
        ai_mean = sum(t["ai"] for t in tasks) / len(tasks)
        robo_mean = sum(t["robo"] for t in tasks) / len(tasks)
        factor = self._seniority_factor(profile)
        ai_score = _clamp(ai_mean * 100 * factor)
        robo_score = _clamp(robo_mean * 100 * factor)
        decomposition = [
            {"id": t["id"], "name": t["name"],
             "ai": round(t["ai"] * 100, 1), "robo": round(t["robo"] * 100, 1),
             "exposed": max(t["ai"], t["robo"]) >= 0.5}
            for t in tasks
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
        trend = self._metro(occ, metro_id).get("demand_trend", "stable")
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

    def _wages(self, occ, metro_id, profile: Profile):
        out: Dict[str, Any] = {"available": False}
        median = self._metro(occ, metro_id).get("median_wage") \
            or occ.get("median_wage_national")
        out["occupation_median_wage"] = median
        out["occupation_wage_trend_5yr_real_pct"] = occ.get("wage_trend_5yr_real_pct")

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
                occ_trend = occ.get("wage_trend_5yr_real_pct")
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

    def _strategies(self, axes, base_exposure, timeline, wages, adjacency, profile) -> List[Dict[str, Any]]:
        """Concrete, data-grounded strategies to protect the person's livelihood, most
        relevant first. Deterministic here; the paid plan expands each with a
        language-model-written, personalised version. Never changes the score."""
        s: List[Dict[str, Any]] = []
        band = timeline.get("band", {}).get("id")

        # 1. Timing, from the timeline band.
        if band == "near_term_high":
            s.append({"title": "Act within the next 1 to 2 years",
                      "detail": "Displacement for this role is near-term. Start a concrete reskilling "
                                "plan now, while you still have income and leverage."})
        elif band == "partial_5_10yr":
            s.append({"title": "Use your 5 to 10 year runway",
                      "detail": "Change here is gradual. Build resilient skills steadily and watch the "
                                "signals rather than waiting for a shock."})
        else:
            s.append({"title": "Stay sharp; urgency is low",
                      "detail": "This role looks durable. Keep your skills current and watch for shifts "
                                "in your field."})

        # 2. The dominant threat axis.
        if axes["ai_software"] >= axes["physical_robotics"] and axes["ai_software"] >= 45:
            s.append({"title": "Lean into the human edge",
                      "detail": "The exposed parts are routine and cognitive. Invest in judgment, client "
                                "relationships, and complex problem-solving that AI still cannot do."})
        elif axes["physical_robotics"] >= 45:
            s.append({"title": "Move up from the task to the system",
                      "detail": "Robotics targets the physical work. Shift toward supervising, maintaining, "
                                "or programming the automation instead of competing with it."})

        # 3. A concrete lower-risk pivot.
        if adjacency:
            a = adjacency[0]
            s.append({"title": f"Pivot toward {a['title']}",
                      "detail": f"It is skill-adjacent and less exposed ({a['max_exposure']} vs "
                                f"{round(base_exposure)}). A lateral move now beats a forced one later."})

        # 4. Financial resilience - the core of avoiding a livelihood shock.
        s.append({"title": "Build a financial buffer",
                  "detail": "Keep 6 to 12 months of expenses and diversify your income, so a disruption "
                            "is a setback rather than a catastrophe."})

        # 5. Wage trajectory.
        if wages.get("available") and (wages.get("real_change_pct") or 0) < 0:
            s.append({"title": "Stop the income slide",
                      "detail": "Your real pay is already falling. Renegotiate, add a credential, or move "
                                "before the erosion compounds."})

        # 6. Protection and credentials.
        if timeline.get("union_protected"):
            s.append({"title": "Use your collective leverage",
                      "detail": "Union coverage can fund retraining and ease transitions. Push for those "
                                "protections while you have them."})
        else:
            s.append({"title": "Add a recognised credential",
                      "detail": "A certification or license raises the bar against automation and signals "
                                "value in a tightening market."})

        # 7. Skills the person listed.
        if profile.skills:
            s.append({"title": "Market your transferable skills",
                      "detail": f"Your skills ({profile.skills}) carry into adjacent roles. Frame them for "
                                "where the work is heading, not just where it has been."})
        return s

    def _adjacency(self, occ, base_exposure) -> List[Dict[str, Any]]:
        out = []
        for adj in occ.get("adjacent", []):
            adj_max = max(adj["ai"], adj["robo"]) * 100
            if adj_max < base_exposure - 0.01:
                out.append({"soc": adj["soc"], "title": adj["title"],
                            "ai_software": round(adj["ai"] * 100, 1),
                            "physical_robotics": round(adj["robo"] * 100, 1),
                            "max_exposure": round(adj_max, 1)})
        out.sort(key=lambda a: a["max_exposure"])
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
    def _load(name):
        with open(DEFAULT_CONFIG_DIR / name, "r", encoding="utf-8") as fh:
            return json.load(fh)
    engine = Engine(snapshot, _load("weights.json"), _load("sources.json"), _load("tiers.json"))
    cal_path = DEFAULT_CONFIG_DIR / "calibration.json"
    engine.calibration = _load("calibration.json") if cal_path.exists() else None
    return engine
