"""Flask app for Jobcast: a JSON API (contract in contracts/api.md) and server-rendered
HTML pages (for SEO and shareable URLs). The scoring is entirely in riskcore; this layer
only reads inputs, calls the engine, and renders."""

import os
import sys
import re
import time
import json
from dataclasses import asdict
from pathlib import Path

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SIGNUP_FILE = Path(__file__).resolve().parents[1] / "data" / "signups.jsonl"

# Reuse a generated plan for similar profiles so we do not re-run the (paid, slow) research
# every time. The research is mostly occupation- and location-specific, so the signature keys
# on what materially shapes the plan: occupation, metro, tier, and a coarse age band - not the
# person's exact skills/experience. Shared across gunicorn workers via an atomic JSON file
# (best-effort; resets on redeploy since the instance disk is ephemeral).
import tempfile  # noqa: E402

_PLAN_CACHE = {}                       # in-process layer; signature -> {"result": {...}, "ts": float}
_PLAN_CACHE_TTL = 60 * 60 * 24 * 30    # 30 days
_PLAN_CACHE_MAX = 500
_PLAN_CACHE_FILE = Path(tempfile.gettempdir()) / "jobcast_plan_cache.json"


def _plan_signature(assessment, profile, tier):
    soc = assessment.get("occupation", {}).get("soc", "?")
    metro = assessment.get("location", {}).get("metro_id", "US")
    age = getattr(profile, "age", None)
    age_band = (age // 10) if isinstance(age, int) else "na"
    return f"{soc}|{metro}|{tier}|{age_band}"


def _cache_file_load():
    try:
        return json.loads(_PLAN_CACHE_FILE.read_text("utf-8"))
    except Exception:
        return {}


def _cache_get(sig):
    hit = _PLAN_CACHE.get(sig)
    if hit is None:
        hit = _cache_file_load().get(sig)
        if hit:
            _PLAN_CACHE[sig] = hit
    if hit and (time.time() - hit.get("ts", 0)) < _PLAN_CACHE_TTL:
        return hit
    return None


def _cache_put(sig, result):
    entry = {"result": result, "ts": time.time()}
    _PLAN_CACHE[sig] = entry
    try:
        data = _cache_file_load()
        data[sig] = entry
        if len(data) > _PLAN_CACHE_MAX:
            for k in sorted(data, key=lambda k: data[k].get("ts", 0))[:len(data) - _PLAN_CACHE_MAX]:
                data.pop(k, None)
        tmp = _PLAN_CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(_PLAN_CACHE_FILE)
    except Exception:
        pass

from flask import Flask, request, jsonify, render_template, redirect, url_for

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from riskcore import Profile, load_default_engine  # noqa: E402
from . import resume as resume_parser  # noqa: E402

VERSION = "0.1.0-dev"


def _num(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def profile_from(source) -> Profile:
    return Profile(
        title=(source.get("title") or "").strip(),
        zip_code=(source.get("zip_code") or source.get("zip") or "").strip() or None,
        age=_num(source.get("age")),
        experience_years=_num(source.get("experience_years")),
        education=(source.get("education") or "").strip() or None,
        education_field=(source.get("education_field") or "").strip() or None,
        skills=(source.get("skills") or "").strip() or None,
        union_status=(source.get("union_status") or "").strip() or None,
        pay_current=_num(source.get("pay_current")),
        pay_5yr_ago=_num(source.get("pay_5yr_ago")),
    )


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024  # 6 MB resume cap
    engine = load_default_engine()

    # Restricted-demo gate (env-controlled, off by default):
    #  JOBCAST_DEMO_USER / JOBCAST_DEMO_PASS -> HTTP basic auth over the whole site.
    #  JOBCAST_NOINDEX=1 -> emit <meta robots noindex> and a preview banner.
    demo_user = os.environ.get("JOBCAST_DEMO_USER")
    demo_pass = os.environ.get("JOBCAST_DEMO_PASS")
    noindex = os.environ.get("JOBCAST_NOINDEX") == "1"

    @app.before_request
    def _gate():
        if not demo_user:
            return None
        auth = request.authorization
        if auth and auth.username == demo_user and auth.password == demo_pass:
            return None
        from flask import Response
        return Response("Authentication required.", 401,
                        {"WWW-Authenticate": 'Basic realm="Jobcast preview"'})

    @app.context_processor
    def _inject():
        return {"noindex": noindex}

    def tier_from_request() -> str:
        header = engine.tiers.get("dev_plan_header", "X-Plan")
        if os.environ.get("JOBCAST_DEV_PLAN_HEADER") == "1":
            requested = request.headers.get(header)
            if requested and any(t["id"] == requested for t in engine.tiers["tiers"]):
                return requested
        return engine.tiers.get("default_tier", "free")

    # ---- JSON API (see contracts/api.md) --------------------------------
    @app.get("/v1/health")
    def health():
        return jsonify({
            "app": "jobcast",
            "version": VERSION,
            "licensed": engine.snapshot.licensed,
            "data_source": engine.snapshot.snapshot_id,
            "snapshot_date": engine.snapshot.snapshot_date,
        })

    @app.get("/v1/suggest")
    def suggest():
        q = request.args.get("q", "")
        return jsonify({"query": q, "suggestions": engine.snapshot.suggest_titles(q)})

    @app.post("/v1/assess")
    def api_assess():
        source = request.get_json(silent=True) or request.form
        result = engine.assess(profile_from(source))
        return jsonify(result), (200 if result.get("ok") else 404)

    @app.post("/v1/whatif")
    def api_whatif():
        body = request.get_json(silent=True) or {}
        profile = profile_from(body.get("profile", {}))
        result = engine.what_if(profile, body.get("overrides", {}))
        return jsonify(result)

    @app.post("/v1/plan")
    def api_plan():
        source = request.get_json(silent=True) or request.form
        result = engine.mitigation_plan(profile_from(source), tier_from_request())
        return jsonify(result)

    @app.post("/v1/advice")
    def api_advice():
        body = request.get_json(silent=True) or request.form
        profile = profile_from(body)
        assessment = engine.assess(profile)
        if not assessment.get("ok"):
            return jsonify({"ok": False, "error": "occupation_not_found"}), 404
        tier = (body.get("tier") or "tier2") if hasattr(body, "get") else "tier2"
        from . import advice as advice_mod

        # Reuse a cached plan for a similar profile when we have a fresh one.
        sig = _plan_signature(assessment, profile, tier)
        hit = _cache_get(sig)
        if hit:
            return jsonify({**hit["result"], "cached": True})

        ai = advice_mod.generate_plan(assessment, asdict(profile), tier=tier)
        if ai and ai.get("steps"):
            result = {"ok": True, "source": "ai", "strategies": ai["steps"],
                      "sources": ai.get("sources", [])}
            _cache_put(sig, result)
            return jsonify({**result, "cached": False})
        n = advice_mod.TIER_N.get(tier, 3)
        return jsonify({"ok": True, "source": "rules",
                        "strategies": assessment.get("strategies", [])[:n], "sources": []})

    # ---- HTML pages -----------------------------------------------------
    def _occupations():
        return [{"soc": o["soc"], "title": o["title"]}
                for o in engine.snapshot.all_occupations()]

    def _rankings(n=20):
        scored = []
        for o in engine.snapshot.all_occupations():
            base = round(max(o.get("ai") or 0, o.get("robo") or 0) * 100)
            scored.append({"soc": o["soc"], "title": o["title"], "base": base})
        most = sorted(scored, key=lambda x: -x["base"])[:n]
        least = sorted(scored, key=lambda x: x["base"])[:n]
        return most, least

    @app.get("/")
    def index():
        most, least = _rankings()
        return render_template("index.html", version=VERSION, licensed=engine.snapshot.licensed,
                               occupations=_occupations(), families=engine.snapshot.families(),
                               most_exposed=most, least_exposed=least,
                               notice=engine.snapshot.data.get("development_notice"))

    @app.post("/assess")
    def assess_page():
        profile = profile_from(request.form)
        result = engine.assess(profile)
        if not result.get("ok"):
            most, least = _rankings()
            return render_template("index.html", version=VERSION, error=result,
                                   occupations=_occupations(), families=engine.snapshot.families(),
                                   most_exposed=most, least_exposed=least,
                                   licensed=engine.snapshot.licensed,
                                   notice=engine.snapshot.data.get("development_notice")), 404
        return render_template("result.html", r=result, profile=profile,
                               profile_json=json.dumps(asdict(profile)), version=VERSION,
                               licensed=engine.snapshot.licensed)

    @app.get("/jobs")
    def browse_jobs():
        return render_template("jobs.html", version=VERSION, licensed=engine.snapshot.licensed,
                               families=engine.snapshot.families())

    @app.get("/jobs/<soc>")
    def occupation_page(soc):
        """Programmatic SEO page: a generic read for an occupation (no personal inputs)."""
        occ = engine.snapshot.occupation(soc)
        if occ is None:
            return redirect(url_for("index"))
        result = engine.assess(Profile(title=occ["title"]))
        return render_template("result.html", r=result, profile=Profile(title=occ["title"]),
                               version=VERSION, licensed=engine.snapshot.licensed, seo=True)

    @app.post("/resume")
    def parse_resume_route():
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"ok": False, "error": "no_file"}), 400
        data = f.read()
        if not data:
            return jsonify({"ok": False, "error": "empty"}), 400
        text = resume_parser.extract_text(f.filename, data)
        if not text or not text.strip():
            return jsonify({"ok": False, "error": "no_text",
                            "message": "Could not read that file. Try a .txt or .docx, or fill the form manually."}), 422
        parsed = resume_parser.parse_resume(text, engine.snapshot)
        return jsonify({"ok": True, **parsed})

    @app.get("/students")
    def students():
        fam = request.args.get("field") or None
        z = request.args.get("education")
        max_zone = int(z) if z and z.isdigit() else None
        priority = request.args.get("priority", "balanced")
        careers = engine.future_careers(family=fam, max_zone=max_zone, priority=priority)
        return render_template("students.html", version=VERSION, licensed=engine.snapshot.licensed,
                               careers=careers, families=engine.snapshot.families(),
                               sel_field=fam, sel_zone=z, sel_priority=priority)

    @app.post("/subscribe")
    def subscribe():
        src = request.get_json(silent=True) or request.form
        email = (src.get("email") or "").strip()
        if not EMAIL_RE.match(email) or len(email) > 254:
            return jsonify({"ok": False, "error": "invalid_email"}), 400
        rec = {"email": email, "context": (src.get("context") or "")[:80], "ts": int(time.time())}
        try:
            SIGNUP_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(SIGNUP_FILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
        except Exception:
            pass
        return jsonify({"ok": True})

    @app.get("/methodology")
    def methodology():
        return render_template("methodology.html", version=VERSION,
                               sources=engine.snapshot.data.get("sources") or engine.sources.get("sources", []),
                               snapshot_id=engine.snapshot.snapshot_id,
                               calibration=getattr(engine, "calibration", None),
                               licensed=engine.snapshot.licensed)

    return app


app = create_app()
