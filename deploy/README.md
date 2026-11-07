# Deploying the Jobcast restricted demo

The serving app needs only Flask (the engine is pure standard library). The committed demo
snapshot (`data/demo/snapshot.json`, real licensed data) ships with the repo, so there is no
build-time data download.

**Restricted-demo gate** (set these on the host):
- `JOBCAST_NOINDEX=1` - emits `noindex` and a "Private preview" banner.
- `JOBCAST_DEMO_USER` / `JOBCAST_DEMO_PASS` - HTTP basic auth over the whole site.
- `JOBCAST_SNAPSHOT` - defaults to the committed demo snapshot; override to point elsewhere.

This is a restricted preview, not a public launch (BUILD_PLAN.md: no public launch until the
entity and privacy policy are settled).

## Prerequisite: the code on a Git host
Any browser PaaS deploys from a Git repo. Put this repo on GitHub (private) first:
- With the GitHub CLI: `gh repo create jobcast --private --source=. --push`
- Or create an empty private repo at github.com, then:
  `git remote add origin <url> && git push -u origin main`

## Option A - Render (simplest browser-only deploy)
1. render.com -> New -> Web Service -> connect the GitHub repo.
2. Render reads `render.yaml` (free plan, `pip install -r requirements-prod.txt`,
   `gunicorn wsgi:app`).
3. In the dashboard, set `JOBCAST_DEMO_USER` and `JOBCAST_DEMO_PASS`.
4. Deploy. The demo is at `https://jobcast-demo.onrender.com` behind basic auth.

## Option B - Google Cloud Run (matches the existing Google/GCE stack)
From the repo (gcloud CLI, or Cloud Shell in the browser):
```
gcloud run deploy jobcast-demo --source . --region us-east1 \
  --allow-unauthenticated \
  --set-env-vars JOBCAST_NOINDEX=1,JOBCAST_DEMO_USER=preview,JOBCAST_DEMO_PASS=<pass>
```
Cloud Run builds the `Dockerfile`, sets `$PORT`, and returns an HTTPS URL. The app's own
basic-auth gate keeps it restricted even with `--allow-unauthenticated`.

## Local production-style check
`gunicorn wsgi:app` on Linux/Mac, or on Windows run `python -m server` (dev server). The WSGI
app, the basic-auth gate, and `noindex` are verified by the smoke test in the session notes.
