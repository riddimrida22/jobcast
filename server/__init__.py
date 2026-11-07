"""Flask app for Jobcast: a JSON API (contract in contracts/api.md) and server-rendered
HTML pages (for SEO and shareable URLs). The scoring is entirely in riskcore; this layer
only reads inputs, calls the engine, and renders."""

import os
import sys
import json
from dataclasses import asdict
from pathlib import Path

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

    @app.get("/methodology")
    def methodology():
        return render_template("methodology.html", version=VERSION,
                               sources=engine.snapshot.data.get("sources") or engine.sources.get("sources", []),
                               snapshot_id=engine.snapshot.snapshot_id,
                               calibration=getattr(engine, "calibration", None),
                               licensed=engine.snapshot.licensed)

    return app


app = create_app()
