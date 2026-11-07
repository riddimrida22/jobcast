# Jobcast

A consumer web tool: enter your job and get an honest, sourced read on whether AI or robots are likely
to replace your work, and when, with the reasoning shown and guidance on what to do. Working name;
see BUILD_PLAN.md for decisions, FACTORS.md for the factor model, GROWTH.md for the growth plan, and
SPEC.md for the original concept.

**Development data only.** v1 runs on a labelled development fixture (illustrative values, not published
figures). `/v1/health` reports `"licensed": false` and every page shows a development banner. Nothing
here is fit for public use yet.

## Layout

```
riskcore/            the engine: mapping, scoring, timeline, wages, adjacency, key drivers, what-if (pure Python, no I/O)
data/fixtures/       snapshot.json: the committed development data snapshot
config/              weights.json (model weights), sources.json (research registry), tiers.json (advice tiers)
server/              Flask API (contracts/api.md) + server-rendered HTML pages
contracts/           api.md, banned_words.json, allowlist.json
tools/               run_server.ps1, banned_check.py, verify_snapshot.py
tests/               pytest, fixture data, no network
```

## Run locally

Any Python 3.10+ with Flask. The engine itself needs only the standard library.

```powershell
pip install -r requirements.txt
.\tools\run_server.ps1                  # http://127.0.0.1:8090
.\tools\run_server.ps1 -DevPlanHeader   # also honor the X-Plan header to preview paid tiers
```

Without the script: `python -m server` from the repo root (set `PYTHONUTF8=1`).

## Checks

```powershell
python -m pytest tests -q          # engine + API tests, fixture data, no network
python tools/verify_snapshot.py    # validate the data snapshot
python tools/banned_check.py       # no-AI-artifacts / house-style check on user-facing strings
```

## Real data ingestion

The engine reads a single dated snapshot. v1 ships two: the committed development fixture, and a real
snapshot built from live sources.

```powershell
# Build the real snapshot (downloads O*NET ~13 MB + Eloundou exposure CSV; CPI via the BLS API):
python -m ingest.build_snapshot
# writes data/snapshots/snapshot-<date>.json

# Run the app on the real snapshot:
$env:JOBCAST_SNAPSHOT = "data/snapshots/snapshot-2026-11-06.json"
python -m server
```

Current real snapshot: 1,016 O*NET 29.1 occupations, marked `licensed: true`. AI/software exposure from
Eloundou et al. (2023) beta; physical/robotics exposure from a transparent proxy over O*NET work-context
physical variables; adjacency from O*NET Related Occupations; CPI live from the BLS API; **national and
metro median wage + employment, the 5-year real wage trend, and a local demand trend (393 metros), from
BLS OEWS (May 2025 and May 2020)**.

**OEWS note:** the BLS public API does not serve OEWS (confirmed with a valid key - every series returns
"No Data Available"), and the BLS website blocks scripted downloads. So the OEWS Excel files are downloaded
through a real browser and placed under `data/cache/oews/` (`oesm25nat.zip`, `oesm20nat.zip`, `oesm25ma.zip`,
`oesm20ma.zip`), then parsed by `ingest/oews_files.py`. A BLS API key (`JOBCAST_BLS_KEY`) is still used for CPI.

**Still to load:** the live job-postings layer and the offline calibration/backtest. The robotics axis is
a work-context proxy, improvable later with a dedicated robot-exposure dataset (e.g. Webb 2020).

## What v1 does

One profile in (field -> job, ZIP, age, experience, education, union status, pay now and five years ago),
one scored, sourced read out: AI/software vs physical/robotics exposure as ranges; a timeline band set
against your remaining working years; the ranked key drivers; the exposed-vs-protected tasks; your wage
trajectory; lower-risk adjacent roles; and a live what-if. Sources and snapshot date are shown on every
result. The paid, tiered mitigation plan (1 or 3 options) is wired as a feature flag; billing is not
built in v1, pending the entity and privacy decisions in BUILD_PLAN.md.

## Not built yet (see BUILD_PLAN.md and FACTORS.md)

The live job-postings layer, the offline calibration and backtesting (statistics/ML) that fits and
validates the weights, billing, and task-level (rather than occupation-level) exposure.

Done: O*NET 29.1 ingestion (1,016 occupations, tasks, work context, related occupations), Eloundou
AI-exposure mapping, the O*NET work-context robotics proxy, live CPI, and BLS OEWS national + metro median
wage, employment, 5-year real wage trend, and local demand trend (393 metros).
