# Jobcast - Build Plan (v1)

Working name: **Jobcast** (domain to confirm; repo stays `AI-Job-Risk-App` until a domain is registered).
This document captures the decisions settled with Bertrand on 2026-11-06 and the plan for a thin v1.
Companion: GROWTH.md (how it gets popular). Concept: SPEC.md. Project rules: CLAUDE.md.

## What it is

A consumer web tool. A person enters their job and a few personal/career facts and gets an honest,
sourced read on whether AI or robots are likely to replace their work, and when, with the reasoning
shown. A small paid upgrade returns an optimal plan to mitigate the risk.

## Decisions settled (2026-11-06)

| Question | Decision |
|---|---|
| Audience / market | Freemium, tiered: free data-driven read; paid mitigation plan in tiers by depth (Tier 1 = 1 option, Tier 2 = 3, Top tier = 5). Build billing last. |
| Platform | Web-first, responsive (one codebase). SEO and shareable URLs are the growth engine. |
| Geography | US first (O*NET / SOC). Taxonomy kept behind a boundary so another country is a data-pack add. |
| Venture / entity | Decide later. Build under working name; settle LLC-vs-P.C. (with accountant/attorney) before any money or public launch. |
| Name | Jobcast (working). Final name + domain confirmed separately by Bertrand. |

## Input model (v1)

Every input must feed a defensible, published-data path. Protected characteristics (gender, race,
disability, etc.) are never inputs to the score.

| Input | What it personalises | Source |
|---|---|---|
| Job title | Core task-exposure score | O*NET -> SOC task list; Frey & Osborne / Eloundou exposure |
| Zip code | Local labour market: is the occupation growing or shrinking in this metro; which lower-risk adjacent roles exist nearby | BLS OEWS (metro/state employment and wages); BLS employment projections |
| Age | The timeline that matters to this person: how much of the automation curve lands inside their remaining working years | Age vs. timeline band (no external data) |
| Years of experience | Seniority shifts the task mix toward less-exposed judgment/management work | O*NET job zone; seniority weighting |
| Education level | Resilience and transition options | O*NET job zone; BLS |
| Current gross pay | Benchmark vs. local/national median for the SOC; higher pay in an exposed role sharpens the timeline | BLS OEWS wage data |
| Pay 5 years ago | Real-terms wage trajectory (deflate with CPI): stagnant real wages are a leading sign of eroding demand | BLS OEWS wage series + BLS CPI |

Self-reported pay is noisy and sensitive: it informs the read and the paid plan but does not dominate the
core exposure score, and it is covered explicitly in the privacy notice.

## Methodology (defensible by construction)

Ground rule from CLAUDE.md: scores come from a transparent model on published data; an LLM never invents a
number. It explains, it does not score.

1. **Map** the job title to a SOC occupation and its O*NET task list (autocomplete over O*NET titles).
2. **Score each task** for AI/software exposure and for physical/robotics exposure, using published
   exposure measures (Eloundou et al. for LLM/software task exposure; Frey & Osborne computerisation
   probability; O*NET work-activity and context attributes for the physical/robotics axis).
3. **Aggregate** task scores into two headline exposures (AI/software, physical/robotics) with stated
   weights.
4. **Adjust** for the person: seniority/experience shifts the task mix; local demand trend and wage
   trajectory shift the timeline band, not the base exposure.
5. **Band the timeline** (e.g. largely unaffected / 5-10 yr partial / near-term high) and set it against
   the person's remaining working years.
6. **Output as a range with confidence**, never a flat verdict. Every number is decomposable to the tasks
   and sources that produced it.

### Defensibility guarantees

- Deterministic engine: same inputs + same data snapshot = same output (reproducible).
- Every score decomposes to task-level contributions and the source behind each.
- Public methodology page: the formula, the weights, the sources, the stated limitations.
- Citations carry a snapshot id and date (e.g. "O*NET v29.0", "BLS OEWS May 2024").
- The LLM appears only in the paid mitigation plan, labelled, reasoning from the person's own pulled data.

## Scenario simulation (what-if)

A person can change an input and re-run to see how the read changes, e.g. "what if I was 20 years
younger?" This is cheap because the engine is deterministic: a what-if is the same scoring run on
modified inputs, with the delta shown against the baseline.

- Allowed what-ifs are constrained to inputs the engine already models on a defensible path: age, years
  of experience, education, pay, zip, or swapping to a target occupation. No free-text hypotheticals that
  would push the model off its sourced data.
- Strong engagement and share hook ("my risk drops from high to moderate if I reskill into X"). Proposed
  as a free feature to drive play and traffic; the full mitigation plan stays paid.
- Each scenario carries the same decomposition and citations as the baseline read.

## Monetisation tiers (advice depth)

Free tier is the read (and what-if). Paid tiers differ by how many mitigation options the plan returns:

| Tier | Mitigation options | Notes |
|---|---|---|
| Free | 0 (read only) | Exposure, timeline, tasks, adjacent roles, what-if. |
| Tier 1 (paid) | 1 | The single best option for this person. |
| Tier 2 | 3 | Top three, ranked. |
| Top tier | 5 | Five options, ranked, with trade-offs. |

The mitigation options are generated by the LLM reasoning from the person's own pulled data (their tasks,
local roles, wage trajectory); the LLM explains and advises, it never scores. Tier is a config flag in
v1; billing is built later, after the entity and privacy questions are settled.

## Validation and calibration (statistics / machine learning)

The factor weights are not guessed and left alone; they are calibrated against real data and the model's
predictions are tested, the same way Eldorado was backtested and independently verified before it was
trusted. This is what makes the aggregate answer for a profile the best available, not just plausible.

- **Calibration (offline).** Fit the factor weights to aggregate outcome data, e.g. regress observed
  occupation employment and real-wage change (BLS historical series) on exposure scores plus controls
  (demand, wages, region). Use interpretable models (regularised regression, GLMs, or gradient boosting
  read with SHAP) so the learned weights stay explainable. The output is the weights in config/weights.json.
- **Backtesting / validation.** Hold-out tests: do occupations we scored high-exposure actually show
  larger subsequent employment or wage decline? Report accuracy and calibration (are our stated ranges
  honest?), and publish the validation summary. A model that does not pass is not shipped.
- **Request-path stays transparent.** The machine learning sets and checks the weights offline. The live
  engine remains a deterministic, decomposable calculation; it is never an opaque per-user black box, and
  every result still traces to tasks and sources.
- **Data flywheel (consented, privacy-safe).** Aggregated, anonymised profile-and-outcome data collected
  through use can refine the calibration over time. This happens offline, never uses protected
  attributes, and never changes the promise that a result is explainable and sourced.
- **Confidence reflects evidence.** The reported range widens where data is thin and narrows where the
  backtest is strong (config/weights.json confidence half-width; wider on the development fixture).

## Dynamic (the engine updates itself)

The premise moves yearly as AI capability advances, so the model is data, not hard-coded logic.

- **Scheduled ingestion, versioned snapshots.** Each source refreshes on its own cadence (O*NET annual;
  BLS OEWS and projections annual/biennial; CPI monthly), pulled by scheduled Python jobs, each snapshot
  stamped with a date. Reuses the scheduled-task pattern already running on these machines.
- **Live layer where it adds value.** Current local job postings near the zip (postings API) show
  real-time demand and real adjacent openings. Reserved for genuinely dynamic data.
- **Research registry.** Model weights and the list of source studies are config, not code. New studies
  are added as weighted inputs without a rewrite; when research shifts, scores shift and we can show why.
- **Re-scoring + "notify me when my score changes"** brings people back and makes it a living forecast.

## Architecture (reuses the Eldorado Insights backbone)

```
engine/        riskcore: mapping, scoring, timeline, adjacency (pure Python, no I/O, fully tested)
data/          versioned source snapshots on disk (gitignored; never committed)
ingest/        scheduled pulls: O*NET, BLS OEWS, BLS projections, CPI, postings (each writes a dated snapshot)
server/        Flask API + server-rendered HTML (Jinja) for SEO; OG-image card generator
contracts/     api.md (the contract), banned_words.json, allowlist.json
tools/         run_server.ps1, banned_check.py, snapshot/verify CLIs
tests/         pytest, synthetic/fixture data, no network
config/         model weights, source registry, free/paid feature flags
```

- **Plan stub (off by default).** Free vs. paid gated by a dev header (as Eldorado's `X-Plan`), replaced by
  a server-side receipt/payment check before any public host. No billing built in v1.
- **banned_check.py** reused: the no-AI-artifacts / plain-language discipline, scanning server strings and
  API responses.
- **Deploy:** GCE, the way the other apps deploy; CDN (Cloudflare) in front for cached public pages.

## Stack (settled)

- Engine + API: Python + **Flask** (the stack already run for Eldorado), pandas/numpy, pytest.
- Frontend: **server-rendered HTML (Flask + Jinja)** for SEO and shareable URLs. Not Flutter (no SEO);
  not a JS framework yet (no new stack). Revisit only if UX demands it.
- Data: dated snapshot files on disk; a small DB only if query needs outgrow files.
- Hosting: GCE + Cloudflare.

## Thin v1 scope

One person's inputs in -> one scored, sourced read out.

In scope:
- Job-title autocomplete -> SOC mapping.
- The seven inputs above.
- Free read: AI/software vs physical/robotics exposure; timeline band vs. remaining working years;
  exposed-vs-protected tasks in plain English; adjacent lower-risk roles present in the person's metro;
  every number with its source and snapshot date; confidence range.
- Public methodology page.
- Shareable result card (URL + OG image).
- Scenario simulation (what-if) over the modelled inputs, with delta vs baseline.
- Tiered mitigation plan (1 / 3 / 5 options) wired as a later feature flag (button present, billing not built).

Out of scope for v1:
- Billing / payments (waits for entity + privacy decisions).
- International occupations.
- Native apps.
- Accounts/login beyond what a result URL needs.

## Privacy and legal guardrails

- Protected demographics never enter the scoring engine.
- Personal-financial inputs (pay) stored with care; a clear privacy notice precedes any public launch.
- Outputs framed as ranges with uncertainty, never "your job is gone."
- Entity (LLC vs P.C.) and a privacy policy settled before taking money or going public.

## Build phases

1. **Engine core** (riskcore): mapping, scoring, timeline, adjacency against a committed fixture snapshot. Tested first.
2. **Data ingestion**: O*NET + BLS OEWS + projections + CPI into dated snapshots; a verify CLI.
3. **API + contract**: Flask endpoints returning the scored, sourced read; contracts/api.md.
4. **Web UI**: input form, result page, methodology page, OG card.
5. **Programmatic occupation pages** (feeds GROWTH.md SEO plan).
6. Later: live postings layer, paid mitigation plan + billing, retention email.

## Open items

- Final name + domain (Bertrand registers).
- Confirm GCE deploy target/domain for this app.
- Data access: confirm O*NET and BLS download/API use (both free, US gov); pick a job-postings API for the live layer.
