"""AI-written mitigation advice. The score is never touched; this only turns the already
computed, structured result into a personalised plan (explanation, not scoring - the one
LLM use the methodology allows).

Activates when an Anthropic API key is present (env JOBCAST_ANTHROPIC_KEY or
ANTHROPIC_API_KEY). With no key or SDK, returns None and the caller falls back to the
deterministic strategies, so nothing breaks.
"""

import os
import sys
import json
from typing import Dict, Any, List, Optional

TIER_N = {"free": 1, "tier1": 1, "tier2": 3, "tier3": 5}

# AI-written advice is reserved for paid tiers; free gets the deterministic strategies.
AI_TIERS = {"tier1", "tier2", "tier3"}

# Model ladder by tier: cheaper models for lower tiers, Opus for the top tier.
MODEL_BY_TIER = {
    "tier1": "claude-haiku-5-5",
    "tier2": "claude-sonnet-5-5",
    "tier3": "claude-opus-4-8",
}


def _context(assessment: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Only structured facts the engine computed, plus banded profile data. No raw PII."""
    w = assessment.get("wages", {})
    t = assessment.get("timeline", {})
    return {
        "occupation": assessment["occupation"]["title"],
        "ai_software_exposure_0_100": assessment["exposure"]["ai_software"],
        "physical_robotics_exposure_0_100": assessment["exposure"]["physical_robotics"],
        "timeline_band": t.get("band", {}).get("label"),
        "local_demand_trend": t.get("local_demand_trend"),
        "remaining_working_years": t.get("remaining_working_years"),
        "union_protected": t.get("union_protected"),
        "key_drivers": [d["label"] + ": " + d["detail"] for d in assessment.get("key_drivers", [])],
        "lower_risk_adjacent_roles": [a["title"] for a in assessment.get("adjacent_lower_risk", [])[:5]],
        "median_wage": w.get("occupation_median_wage"),
        "my_real_pay_change_pct_5yr": w.get("real_change_pct"),
        "my_pay_vs_local_median_pct": w.get("pay_vs_median_pct"),
        "my_skills": profile.get("skills"),
        "my_field_of_study": profile.get("education_field"),
        "my_education": profile.get("education"),
    }


ICONS = {"skill", "pivot", "buffer", "network", "credential", "automate"}
HORIZONS = {"Now", "0-6 months", "6-18 months", "1-3 years"}
LEVELS = {"High", "Medium", "Low"}

SYSTEM = (
    "You are a careful career strategist for JobBreak. Using ONLY the facts in the user message, produce "
    "{n} concrete, personalised steps to protect this person's livelihood from automation, most important "
    "first. Hard rules: never invent statistics, probabilities, or numbers; reference only the facts given; "
    "frame everything as options, never a certainty that a job will be lost; name the adjacent roles and "
    "the person's own skills and field where relevant. Keep words minimal and meaningful - a card, not a "
    "paragraph. Output STRICT JSON only: an array of objects, each with keys "
    "\"headline\" (2 to 4 words), "
    "\"action\" (one imperative sentence, at most 16 words), "
    "\"horizon\" (exactly one of: Now, 0-6 months, 6-18 months, 1-3 years), "
    "\"impact\" (exactly one of: High, Medium, Low - how much this protects their livelihood), "
    "\"effort\" (exactly one of: Low, Medium, High), "
    "\"icon\" (exactly one of: skill, pivot, buffer, network, credential, automate - the closest match). "
    "No text outside the JSON."
)


def generate_plan(assessment: Dict[str, Any], profile: Dict[str, Any],
                  tier: str = "tier2", api_key: Optional[str] = None) -> Optional[List[Dict[str, str]]]:
    api_key = api_key or os.environ.get("JOBCAST_ANTHROPIC_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[advice] no API key in env; using deterministic fallback", file=sys.stderr, flush=True)
        return None
    if tier not in AI_TIERS:
        print(f"[advice] tier '{tier}' not AI-eligible; deterministic advice", file=sys.stderr, flush=True)
        return None
    try:
        import anthropic
    except Exception as e:
        print(f"[advice] anthropic import failed: {e}; fallback", file=sys.stderr, flush=True)
        return None
    n = TIER_N.get(tier, 3)
    model = MODEL_BY_TIER.get(tier, "claude-haiku-5-5")
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model, max_tokens=min(4000, 600 + 400 * n),
            system=SYSTEM.format(n=n),
            messages=[{"role": "user", "content": json.dumps(_context(assessment, profile))}])
        text = "".join(getattr(b, "text", "") for b in msg.content)
        arr = json.loads(text[text.find("["):text.rfind("]") + 1])
        out = []
        for x in arr:
            head = str(x.get("headline") or x.get("title") or "").strip()
            if not head:
                continue
            act = str(x.get("action") or x.get("detail") or "").strip()
            out.append({
                "headline": head,
                "action": act,
                "horizon": x.get("horizon") if x.get("horizon") in HORIZONS else "6-18 months",
                "impact": x.get("impact") if x.get("impact") in LEVELS else "High",
                "effort": x.get("effort") if x.get("effort") in LEVELS else "Medium",
                "icon": x.get("icon") if x.get("icon") in ICONS else "skill",
                # back-compat for any text consumer
                "title": head, "detail": act,
            })
        return out[:n] or None
    except Exception as e:
        print(f"[advice] API call failed ({type(e).__name__}): {e}; fallback", file=sys.stderr, flush=True)
        return None
