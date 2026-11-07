"""AI-written mitigation advice. The score is never touched; this only turns the already
computed, structured result into a personalised plan (explanation, not scoring - the one
LLM use the methodology allows).

Activates when an Anthropic API key is present (env JOBCAST_ANTHROPIC_KEY or
ANTHROPIC_API_KEY). With no key or SDK, returns None and the caller falls back to the
deterministic strategies, so nothing breaks.
"""

import os
import json
from typing import Dict, Any, List, Optional

TIER_N = {"free": 1, "tier1": 1, "tier2": 3}


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


SYSTEM = (
    "You are a careful career strategist for Jobcast. Using ONLY the facts in the user message, write "
    "{n} concrete, personalised strategies to protect this person's livelihood from automation and avoid "
    "financial hardship, most important first. Hard rules: never invent statistics, probabilities, or "
    "numbers; reference only the facts given; frame everything as options and ranges, never a certainty "
    "that a job will be lost; be specific and actionable, naming the adjacent roles and the person's own "
    "skills and field where relevant, with rough timeframes. Output STRICT JSON only: a JSON array of "
    "objects each with keys \"title\" (short) and \"detail\" (2-3 sentences). No text outside the JSON."
)


def generate_plan(assessment: Dict[str, Any], profile: Dict[str, Any],
                  tier: str = "tier2", api_key: Optional[str] = None) -> Optional[List[Dict[str, str]]]:
    api_key = api_key or os.environ.get("JOBCAST_ANTHROPIC_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except Exception:
        return None
    n = TIER_N.get(tier, 3)
    model = "claude-opus-4-8" if tier == "tier2" else "claude-haiku-5-5"
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model, max_tokens=1300, temperature=0.4,
            system=SYSTEM.format(n=n),
            messages=[{"role": "user", "content": json.dumps(_context(assessment, profile))}])
        text = "".join(getattr(b, "text", "") for b in msg.content)
        arr = json.loads(text[text.find("["):text.rfind("]") + 1])
        out = [{"title": str(x.get("title", "")).strip(), "detail": str(x.get("detail", "")).strip()}
               for x in arr if x.get("title")]
        return out[:n] or None
    except Exception:
        return None
