# Jobcast - Factor Model

The goal is the best, most honest job-automation tool. That means being comprehensive, but under one
rule from CLAUDE.md: every factor must trace to published data or research and have a defined effect.
A factor with no credible source is left out, because it would make the tool less defensible, not more.

Each factor below lists:
- **Effect**: does it move the base exposure SCORE, the TIMELINE, or the ADVICE? (Base score comes only
  from task exposure; personal and institutional factors move timeline and advice, never the base score.)
- **Source**: the published data or research behind it.
- **Phase**: v1 (wired now), v1.x (next), or later.

## Principle: conditional applicability (the pyramid funnel)

Factors are not all relevant to everyone. Each factor carries an applicability condition on the profile
and the occupation, and only contributes when it applies:

- Union coverage applies where the role is unionisable; it is decisive for a driver or nurse, marginal
  for a solo consultant.
- Occupational licensing applies to licensed professions (lawyer, nurse), not to data entry.
- Wage trajectory applies only when the person provides current and prior pay.
- Remote-ability applies to desk/knowledge roles.
- Automation ROI matters most where pay is high relative to the median.

This is the funnel Bertrand described: start at the broad base (general field, the full input set) and
narrow to the few factors that actually move THIS person's result. The engine implements the apex as a
ranked `key_drivers` list, where a factor appears only when its condition fires. Input-side progressive
disclosure (asking only the questions that matter for the chosen occupation) is a v1.x step; the data
model carries per-occupation applicability flags to drive it.

## A. Occupation and task factors (drive the base exposure score)

| Factor | Effect | Source | Phase |
|---|---|---|---|
| Task composition of the occupation | SCORE | O*NET task list | v1 |
| Per-task AI/software exposure | SCORE (AI axis) | Eloundou et al. 2023 | v1 |
| Per-task physical/robotics exposure | SCORE (robotics axis) | O*NET work context + robotics literature | v1 |
| Routine vs non-routine, manual vs cognitive | SCORE | Autor/Levy/Murnane framework | v1.x |
| Engineering bottlenecks: perception and manipulation, creativity, social intelligence | SCORE (caps exposure) | Frey & Osborne 2013 | v1.x |
| Degree of in-person human interaction / caregiving | SCORE (lowers) | O*NET work context | v1.x |
| Unstructured vs structured physical environment | SCORE (robotics) | O*NET work context | v1.x |
| Fine dexterity / manipulation demands | SCORE (robotics, lowers) | O*NET abilities | v1.x |
| Judgment, accountability, ethical/legal responsibility | SCORE (lowers) | O*NET + Frey & Osborne | v1.x |
| Data availability to train AI in the domain | SCORE | research registry | later |

## B. Technology trajectory factors (how fast exposure becomes displacement)

| Factor | Effect | Source | Phase |
|---|---|---|---|
| Current frontier AI capability vs the task | SCORE/TIMELINE | Eloundou; updated via research registry | v1 (static), later (live) |
| Rate of AI capability progress | TIMELINE | research registry (re-weighted over time) | later |
| Robotics cost and capability curve | TIMELINE | industry/robotics reports | later |
| Automation cost vs labour cost (ROI to automate) | TIMELINE | derived from wages | v1.x |

## C. Labour-market factors (local and national)

| Factor | Effect | Source | Phase |
|---|---|---|---|
| Local occupation demand trend (growing/stable/declining) | TIMELINE | BLS projections, OEWS | v1 |
| Employment level/concentration in the metro | ADVICE | BLS OEWS | v1 |
| Occupation wage level vs median | TIMELINE (ROI) | BLS OEWS | v1 |
| Personal real wage trajectory (5-yr, CPI-adjusted) | TIMELINE/ADVICE | BLS OEWS + CPI | v1 |
| Job openings and turnover near the user | ADVICE | job-postings API | later (live layer) |
| Metro industry mix | ADVICE | BLS | later |
| Remote-ability of the work | SCORE/ADVICE | Dingel & Neiman 2020 | v1.x |
| Offshorability (distinct from automation) | ADVICE | Blinder offshorability index | later |
| Sector: public vs private, firm size | TIMELINE | BLS; research | later |

## D. Personal / worker factors (move timeline and advice, never the base score)

| Factor | Effect | Source | Phase |
|---|---|---|---|
| Age -> remaining working years | TIMELINE overlap | user input + retirement age | v1 |
| Experience / seniority | SCORE adjustment (task mix to oversight) | O*NET job zone + weighting | v1 |
| Education level | ADVICE / resilience | O*NET job zone, BLS | v1 |
| Transferable / specialised skills | ADVICE | O*NET skills, skills-adjacency | v1.x |
| Management responsibility | SCORE adjustment | O*NET | v1.x |
| Certifications and licences held | TIMELINE/ADVICE | O*NET, licensing data | later |
| Geographic mobility / willingness to relocate | ADVICE | user input | v1.x |
| Tenure with current employer | ADVICE | user input | later |
| Self-employed vs employee | TIMELINE/ADVICE | user input | later |

## E. Protective / institutional factors (slow displacement)

| Factor | Effect | Source | Phase |
|---|---|---|---|
| Union membership / collective-bargaining coverage | TIMELINE (slows) | labour-economics research; BLS union data | v1 |
| Occupational licensing | TIMELINE (slows) | licensing data | v1.x |
| Regulation mandating human involvement/sign-off | TIMELINE (slows) | sector regulation | later |
| Professional liability requiring a human | TIMELINE (slows) | sector/research | later |
| Public-sector employment stability | TIMELINE | BLS | later |

## F. Deliberately excluded from the score (sensitive / indefensible)

These are never inputs to the risk score. There is no published model that scores automation risk by
these attributes, and doing so would be discriminatory profiling of someone's career.

- Gender, race, ethnicity, religion, national origin, sexual orientation, disability, health status,
  immigration status, marital/family status.
- Age is used **only** to compute remaining working years for the timeline overlap, never to raise or
  lower exposure.

If any demographics are ever collected, it is for optional, consented, aggregate equity analytics kept
entirely out of the scoring engine, and disclosed in the privacy notice.

## Scoring architecture (how the factors combine)

1. **Base exposure** (two axes, 0-100) from task-level AI and robotics exposure. Group A only.
2. **Score adjustments**: seniority/experience and management shift the task mix. Still group A/D, bounded.
3. **Timeline**: base exposure banded, then shifted by local demand (C), automation ROI from wages (B/C),
   union and institutional protection (E), and read against remaining working years (D).
4. **Advice** (paid tiers): adjacency and skills (A/D) plus local opportunities (C), explained by a
   language model that reasons from the pulled data. The model explains; it never sets a number.

Every output stays a range with stated confidence, every number decomposes to its factors and sources,
and the factor weights live in config (see config/weights.json, BUILD_PLAN.md research registry) so the
model can be tuned and audited without a code change.
