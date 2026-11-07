# Jobcast API contract (v1, development)

Base: `http://127.0.0.1:8090`. All responses are JSON unless a route renders HTML.
Development only: `licensed` is `false` and values come from the development fixture.

## Conventions
- Errors: `{ "ok": false, "error": "<code>", "message": "<sentence>" }`.
- Inputs accept JSON body or form fields: `title`, `zip` (or `zip_code`), `age`, `experience_years`,
  `education`, `union_status` ("yes"|"no"), `pay_current`, `pay_5yr_ago`.
- Protected characteristics are never accepted as scoring inputs.

## GET /v1/health
`{ "app": "jobcast", "version", "licensed", "data_source", "snapshot_date" }`

## GET /v1/suggest?q=<text>
`{ "query", "suggestions": [ { "soc", "title" } ] }` - job-title autocomplete.

## POST /v1/assess
Body: a profile (fields above; only `title` is required).
200 `{ "ok": true, "occupation", "location", "exposure": { "ai_software", "physical_robotics" },
"exposure_range", "base_exposure", "key_drivers": [...], "timeline", "tasks": [...], "wages",
"adjacent_lower_risk": [...], "sources": [...], "snapshot" }`.
404 `{ "ok": false, "error": "occupation_not_found", "suggestions": [...] }`.

## POST /v1/whatif
Body: `{ "profile": {...}, "overrides": { "age"|"experience_years"|"education"|"union_status"|
"pay_current"|"pay_5yr_ago"|"zip_code"|"title": value } }`.
Returns `{ "ok", "overrides", "baseline": <assess>, "scenario": <assess>, "deltas": { "ai_software",
"physical_robotics", "timeline_band_from", "timeline_band_to" } }`.
Overrides are limited to modelled fields; an unknown field is rejected.

## POST /v1/plan
Body: a profile. Tier comes from the `X-Plan` header when `JOBCAST_DEV_PLAN_HEADER=1` (dev only),
else `free`. Returns `{ "ok", "tier", "options_count", "options": [ { "move_to", "why", "detail" } ] }`.
Free returns zero options. Billing is not implemented in v1.

## HTML routes
- `GET /` - the input form (field -> job cascade, dropdowns, searchable job picker).
- `POST /assess` - renders the result page.
- `GET /jobs` - browse all jobs by field.
- `GET /jobs/<soc>` - a job's public page (programmatic SEO; generic, no personal inputs).
- `GET /methodology` - how the model works and its sources.
