"""AI-written mitigation advice. The score is never touched; this only turns the already
computed, structured result into a personalised plan (explanation, not scoring - the one
LLM use the methodology allows).

For the research tiers, Claude may use the web-search tool to gather real, current, cited
insights (demand, pay, training pathways, transition outcomes, local resources) specific to
the person, and must cite them. It is never allowed to invent figures: every specific number
or claim must come from a search result it cites, or from the structured facts provided.

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

# Live web research is reserved for the higher paid tiers (cost + latency).
RESEARCH_TIERS = {"tier2", "tier3"}

# Model ladder by tier: cheaper models for lower tiers, Opus for the top tier.
MODEL_BY_TIER = {
    "tier1": "claude-haiku-5-5",
    "tier2": "claude-sonnet-5-5",
    "tier3": "claude-opus-4-8",
}


def _context(assessment: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Structured facts the engine computed, plus banded profile data. No raw PII beyond
    what the person typed (age band / experience / skills), which they entered themselves."""
    w = assessment.get("wages", {})
    t = assessment.get("timeline", {})
    loc = assessment.get("location", {})
    return {
        "occupation": assessment["occupation"]["title"],
        "occupation_family": assessment["occupation"].get("family"),
        "location": loc.get("metro"),
        "age": profile.get("age"),
        "years_of_experience": profile.get("experience_years"),
        "union_status": profile.get("union_status"),
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

_SCHEMA = (
    "Output STRICT JSON only: an array of {n} objects, each with keys "
    "\"headline\" (2 to 4 words), "
    "\"action\" (one imperative sentence, at most 16 words), "
    "\"evidence\" (one concrete, specific insight that makes this smarter than a generic web search, "
    "at most 18 words; empty string if you have none), "
    "\"source\" (the name of the real publication/site the evidence came from, e.g. 'BLS' or "
    "'Austin Community College'; empty string if the step uses no external figure), "
    "\"horizon\" (exactly one of: Now, 0-6 months, 6-18 months, 1-3 years), "
    "\"impact\" (exactly one of: High, Medium, Low - how much this protects their livelihood), "
    "\"effort\" (exactly one of: Low, Medium, High), "
    "\"icon\" (exactly one of: skill, pivot, buffer, network, credential, automate - the closest match). "
    "No text outside the JSON."
)

SYSTEM = (
    "You are a careful career strategist for JobBreak. Using ONLY the facts in the user message, produce "
    "{n} concrete, personalised steps to protect this person's livelihood from automation, most important "
    "first. Hard rules: never invent statistics, probabilities, or numbers; reference only the facts given; "
    "frame everything as options, never a certainty that a job will be lost; name the adjacent roles and "
    "the person's own skills and field where relevant. Keep words minimal and meaningful - a card, not a "
    "paragraph. Leave \"evidence\" and \"source\" empty. " + _SCHEMA
)

RESEARCH_SYSTEM = (
    "You are a sharp, resourceful career strategist for JobBreak. Your job is to give this specific person "
    "advice far better than a generic web search: tailored to their occupation, age, experience, location, "
    "and skills, connecting dots they would not find themselves. Use the web_search tool to gather REAL, "
    "CURRENT, CITED facts relevant to THEM - local and national demand, concrete transition pathways from "
    "their job, specific training programs or apprenticeships (ideally near their location), typical pay and "
    "outcomes, and how workers like them have adapted. Then produce {n} concrete, personalised steps, most "
    "important first. Absolute rules: never fabricate a number, rate, or claim - every specific figure must "
    "come from a source you actually searched, named in \"source\"; frame everything as options and ranges, "
    "never a certainty that a job will be lost. Put the single most useful, specific, sourced insight for "
    "each step in \"evidence\" (concrete, not generic). Keep words minimal. " + _SCHEMA
)


def _parse_steps(text: str, n: int) -> List[Dict[str, str]]:
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
            "evidence": str(x.get("evidence") or "").strip(),
            "source": str(x.get("source") or "").strip(),
            "horizon": x.get("horizon") if x.get("horizon") in HORIZONS else "6-18 months",
            "impact": x.get("impact") if x.get("impact") in LEVELS else "High",
            "effort": x.get("effort") if x.get("effort") in LEVELS else "Medium",
            "icon": x.get("icon") if x.get("icon") in ICONS else "skill",
            "title": head, "detail": act,  # back-compat
        })
    return out[:n]


def _collect(msg) -> (str, List[Dict[str, str]]):
    """Final text plus a de-duplicated list of {title, url} web-search citations."""
    text, seen, sources = "", set(), []
    for block in msg.content:
        t = getattr(block, "text", None)
        if t:
            text += t
        for cit in (getattr(block, "citations", None) or []):
            url = getattr(cit, "url", None)
            if url and url not in seen:
                seen.add(url)
                sources.append({"title": getattr(cit, "title", "") or url, "url": url})
    return text, sources


def generate_plan(assessment: Dict[str, Any], profile: Dict[str, Any],
                  tier: str = "tier2", api_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Returns {"steps": [...], "sources": [...]} or None (caller falls back to rules)."""
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
    research = tier in RESEARCH_TIERS
    content = json.dumps(_context(assessment, profile))
    client = anthropic.Anthropic(api_key=api_key)

    def call(use_search: bool):
        kwargs = dict(
            model=model, max_tokens=min(5000, 900 + 450 * n),
            system=(RESEARCH_SYSTEM if use_search else SYSTEM).format(n=n),
            messages=[{"role": "user", "content": content}],
        )
        if use_search:
            kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
        return client.messages.create(**kwargs)

    # Try research first (if eligible); fall back to a plain call, then to rules.
    for use_search in ([True, False] if research else [False]):
        try:
            msg = call(use_search)
            text, sources = _collect(msg)
            steps = _parse_steps(text, n)
            if steps:
                mode = "ai+research" if use_search else "ai"
                print(f"[advice] {mode} ok: {len(steps)} steps, {len(sources)} sources", file=sys.stderr, flush=True)
                return {"steps": steps, "sources": sources}
        except Exception as e:
            print(f"[advice] {'research' if use_search else 'plain'} call failed "
                  f"({type(e).__name__}): {e}", file=sys.stderr, flush=True)
    return None
