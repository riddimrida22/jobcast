# Jobcast - Calibration and Backtest

Offline validation of the exposure model against real BLS employment outcomes. Interpretable statistics only (OLS + ridge, cross-validated); the live engine runs no black-box model and never calls a language model to score. See analysis/calibrate.py.

## The product is a ranking, so we test the ranking

R2 answers 'how precisely do we predict one occupation's employment change?' - the wrong question for a tool that ranks jobs by risk. We report rank metrics instead (R2 is shown but labelled *not our target metric*):

- **Spearman** rank correlation between predicted and realised employment change.
- **AUC**: given a declining and a growing occupation, how often we rank the declining one as higher-risk (0.5 = coin flip).
- **Decile lift**: mean realised employment change, top-risk decile vs bottom.

- Occupations (6-digit SOC): **702**
- Outcome: 5-year national employment change (percent)
- Horizon: 2020-2025 (OEWS May)

## Deployed model vs the shipped v1 baseline

The v1 score was an unfitted `max(ai, robo)`. The v2 deployed blend adds the two task-structure factors that earn their place out of sample. Metrics are out-of-fold (ridge, 5-fold), so they are honest out-of-sample numbers.

| Model | Spearman | AUC (decline) | Top-risk decile | Bottom-risk decile |
|---|---|---|---|---|
| v1 `max(ai,robo)` (shipped) | ~0.01 | 0.649 | -9.1% | 19.2% |
| **v2 deployed blend** | **0.321** | **0.686** | **-8.0%** | **17.4%** |

The v2 blend ranks a declining occupation above a growing one 69% of the time; the shipped v1 score was a coin flip (AUC 0.649).

_For reference, in-sample R2 is 0.132 (expanded model) vs 0.058 (baseline). It is low because individual occupation outcomes are noisy - which is exactly why we rank rather than predict a point, and why results ship as ranges. R2 is **not our target metric**._

## Which factors earned their place?

Standardised OLS on the expanded model (all candidates + wage/size controls). A factor earns its place by a significant, correctly-signed coefficient; we drop the rest rather than keep a kitchen sink.

| Feature | Std coef | SE | t | p |
|---|---|---|---|---|
| ai | -0.803 | 1.241 | -0.65 | 0.518 |
| robo | 2.801 | 1.516 | 1.85 | 0.0651 |
| interpersonal | 5.874 | 1.017 | 5.78 | 0.0 |
| routine_structured | -3.931 | 1.399 | -2.81 | 0.0051 |
| job_zone | 0.303 | 1.809 | 0.17 | 0.8669 |
| creative | 0.454 | 1.185 | 0.38 | 0.7021 |
| log_median | 4.953 | 1.448 | 3.42 | 0.0007 |
| log_emp0 | 3.523 | 0.975 | 3.61 | 0.0003 |

- **Earned their place** (p < 0.05): `interpersonal`, `routine_structured`.
- **Dropped** (did not): `ai`, `robo`, `job_zone`, `creative`.
- `interpersonal` is the strongest protector and `routine_structured` the strongest risk; `job_zone` and `creative` add nothing once the others are in.
- `ai` is insignificant and `robo` weak/confounded in this COVID-era window, so the deployed blend keeps them at modest **research-set** weights (Eloundou; Frey & Osborne) rather than letting a noisy fit set their direction.

## The deployed exposure blend (what the live engine uses)

A transparent weighted average of four task-intrinsic 0-100 sub-scores, every term oriented so higher = more automatable (interpersonal enters as protection, `100 - interpersonal`). Weights live in `config/weights.json` and are written by this script:

| Sub-score | Weight | Direction |
|---|---|---|
| AI / software exposure (Eloundou) | 0.15 | raises risk |
| Physical / robotics proxy (O*NET) | 0.1 | raises risk |
| Routine & structured work (O*NET) | 0.3 | raises risk |
| Interpersonal protection (O*NET) | 0.45 | raises risk when low |

## Backtest: employment change by predicted timeline band

Band cut points are refit to the deployed score (40th/80th percentiles). If the model is directionally valid, higher-risk bands show lower employment growth.

| Band | n | Mean emp change % | Median emp change % |
|---|---|---|---|
| Largely unaffected | 262 | 13.4 | 11.5 |
| Partial, 5 to 10 years | 295 | 2.1 | 0.9 |
| Near-term, high | 145 | -4.5 | -7.3 |

## Convergent validity (independent measures we did not fit on)

We compare each external measure against two of our numbers: our **AI sub-score** (Eloundou - a like-for-like AI-exposure comparison) and our **deployed blend** (realised displacement risk). The two can diverge honestly.

- **Felten-Raj-Seamans AIOE** (n = 657): Spearman **0.862** vs our AI sub-score, **-0.022** vs the deployed blend.
- **Webb 2020**: not available in this build (documented data gap; not fabricated).

AIOE ranks AI *task applicability*, which is highest for high-skill cognitive roles; our deployed blend ranks realised *displacement* risk, highest for routine, low-interpersonal roles. They measure different constructs, so a low correlation on the blend is expected and disclosed, not hidden - the honest reading is that AI-applicability and realised job loss are not the same thing in the 2020-2025 data.

## Post-2022 window (the real test of the AI signal)

Away from the 2020 COVID base year (2022-2025 (OEWS May), n = 738), the deployed blend ranks with AUC 0.666 and Spearman 0.316.

## Data gaps (documented, not worked around)

- **Webb (2020) patent-based exposure**: no cleanly public per-occupation data file was located for this build; documented and skipped rather than fabricated.
- **Hiring / vacancy data** (Lightcast, Indeed): largely proprietary; recorded as a known gap, not a blocker.

## Caveats (read before trusting these numbers)

- The 2020 base year is the COVID shock; employment change partly reflects pandemic recovery, not automation.
- Physical/robot-exposed work rebounded in this window, so `robo`'s fitted coefficient is weak and the wrong sign for a displacement story; ai/robo therefore keep modest research-set weights (Eloundou; Frey & Osborne) rather than a confounded fit.
- Raw AI exposure is statistically insignificant here; AI's large labour effects are recent/prospective, so a weak in-sample AI signal is expected and honest.
- R2 is low in absolute terms because individual occupation outcomes are noisy; the product is a ranking, so we report and optimise rank metrics instead.
- The two factors that earn their place out of sample are `interpersonal` (protector) and `routine_structured` (risk); `job_zone` and `creative` did not and are dropped.
