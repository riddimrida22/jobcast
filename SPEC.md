# AI/Robot Job-Replacement App — concept spec (kickoff)

Working folder only; product name to be decided with Bertrand.

## What it is
A consumer-facing app where a person enters their job and gets an honest read on
**whether** AI or robots are likely to take over their work, and **when**, with the
reasoning shown and concrete "what to do about it" guidance.

## Core user flow (v1 target)
1. User types or picks their job title (autocomplete).
2. App maps that title to a standard occupation (O*NET / SOC code) and its task list.
3. App shows:
   - An automation-exposure score (0-100) split into **AI/software** vs **physical/robotics** exposure.
   - A rough **timeline** band (e.g. "largely unaffected", "5-10 yr partial", "near-term high").
   - **Why**: which of the job's tasks are exposed vs protected, in plain language.
   - **What to do**: adjacent lower-risk roles, skills that raise resilience.
4. Shareable result card.

## Methodology must be defensible (this is the main credibility risk)
Predictions about people's livelihoods will be judged harshly if they look made up.
Ground the scores in published research and real task data, cite sources in-app, and
frame outputs as probabilities/ranges, not verdicts. Candidate bases:
- O*NET task and skill data (free, US gov) for the per-job task breakdown.
- Frey & Osborne (2013) computerisation probabilities.
- Eloundou et al. (2023, "GPTs are GPTs") LLM task-exposure.
- McKinsey / OECD / WEF automation and Future-of-Jobs reports.
Blend into a transparent scoring model rather than asking an LLM to guess a number.

## Open questions for Bertrand (resolve in-session before building)
- Audience/market: free public tool, or a commercial product (like Eldorado Insights)?
- Platform: web-first (desktop + mobile web) vs iPhone-first native?
- Geography: US occupation data first, or international from the start?
- Monetisation / is this an Aquatech venture or a separate LLC?
- Name and domain.
- Tech stack (default proposal: static-data + web app; reuse the stack Bertrand already runs).

## Status
Greenfield. Nothing built yet. Start by confirming the open questions, then a thin v1:
one job -> one scored, sourced result.
