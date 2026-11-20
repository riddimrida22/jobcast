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

from flask import Flask, request, jsonify, render_template, redirect, url_for, session, g, Response

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
    from flask import g
    return Profile(
        title=(source.get("title") or "").strip(),
        country=(source.get("country") or "").strip() or getattr(g, "country", None),
        zip_code=(source.get("zip_code") or source.get("zip") or "").strip() or None,
        age=_num(source.get("age")),
        experience_years=_num(source.get("experience_years")),
        education=(source.get("education") or "").strip() or None,
        education_field=(source.get("education_field") or "").strip() or None,
        skills=(source.get("skills") or "").strip() or None,
        union_status=(source.get("union_status") or "").strip() or None,
        pay_current=_num(source.get("pay_current")),
        pay_5yr_ago=_num(source.get("pay_5yr_ago")),
        graduation_year=_num(source.get("graduation_year")),
        sector=(source.get("sector") or "").strip() or None,
    )


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024  # 6 MB resume cap
    engine = load_default_engine()

    # Restricted-demo gate (env-controlled, off by default):
    #  JOBCAST_DEMO_USER / JOBCAST_DEMO_PASS -> branded login page over the whole site,
    #    with a cookie-backed session (replaces the old HTTP basic-auth popup, so we can
    #    style sign-in and offer a show/hide password toggle).
    #  JOBCAST_SECRET -> signing key for the session cookie (falls back to a stable value
    #    derived from the demo password so sessions survive restarts without extra config).
    #  JOBCAST_NOINDEX=1 -> emit <meta robots noindex> and a preview banner.
    demo_user = os.environ.get("JOBCAST_DEMO_USER")
    demo_pass = os.environ.get("JOBCAST_DEMO_PASS")
    noindex = os.environ.get("JOBCAST_NOINDEX") == "1"
    app.secret_key = os.environ.get("JOBCAST_SECRET") or ("jobcast-preview-" + (demo_pass or "dev"))

    @app.before_request
    def _gate():
        if not demo_user:
            return None
        if request.endpoint in ("login", "static", "manifest", "service_worker", "stripe_webhook",
                                "privacy", "terms", "admin_stats"):
            return None
        if session.get("jb_authed"):
            return None
        return redirect(url_for("login", next=request.full_path if request.query_string else request.path))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not demo_user:
            return redirect(url_for("index"))
        if session.get("jb_authed"):
            return redirect(url_for("index"))
        nxt = request.values.get("next") or "/"
        if not nxt.startswith("/"):   # only ever redirect to a local path
            nxt = "/"
        error = None
        if request.method == "POST":
            u = (request.form.get("username") or "").strip()
            p = request.form.get("password") or ""
            if u == demo_user and p == demo_pass:
                session["jb_authed"] = True
                session.permanent = True
                return redirect(nxt)
            error = "Incorrect username or password. Please try again."
        return render_template("login.html", error=error, next=nxt)

    @app.context_processor
    def _inject():
        from . import payments as pay
        return {"noindex": noindex, "stripe_enabled": pay.configured(),
                "entitlement": session.get("jb_tier", "free"),
                # Ad-platform tags (Meta Pixel, Google Ads). Dormant until the IDs are set as
                # env vars, so nothing loads or changes on the site until an ad account exists.
                "meta_pixel_id": os.environ.get("JOBCAST_META_PIXEL_ID", ""),
                "google_ads_id": os.environ.get("JOBCAST_GOOGLE_ADS_ID", ""),
                "google_conversion_label": os.environ.get("JOBCAST_GOOGLE_CONVERSION_LABEL", ""),
                # Consumer-facing name for the 0-100 rating. One place to change it.
                "rating_label": "Job Extinction Risk"}

    @app.after_request
    def _track(resp):
        """First-party page-view analytics. Best-effort; never breaks a response."""
        try:
            if request.method != "GET" or resp.status_code != 200:
                return resp
            if not (resp.content_type or "").startswith("text/html"):
                return resp
            p = request.path or "/"
            if (p.startswith(("/static", "/webhooks", "/tasks", "/v1", "/admin"))
                    or p in ("/robots.txt", "/sitemap.xml", "/sw.js", "/manifest.webmanifest", "/login")
                    or p.endswith("card.png")):
                return resp
            ua = request.headers.get("User-Agent", "")
            ual = ua.lower()
            if any(b in ual for b in ("bot", "spider", "crawl", "slurp", "bingpreview",
                                      "facebookexternalhit", "headless", "python-", "curl", "wget")):
                return resp
            import hashlib
            from urllib.parse import urlparse
            xff = request.headers.get("X-Forwarded-For", "")
            ip = (xff.split(",")[0].strip() if xff else (request.remote_addr or ""))
            day = time.strftime("%Y-%m-%d", time.gmtime())
            vid = hashlib.sha256(f"{ip}|{ua}|{day}|{app.secret_key}".encode("utf-8", "ignore")).hexdigest()[:16]
            ref_host = ""
            r = request.referrer or ""
            if r:
                try:
                    h = urlparse(r).netloc.lower()
                    if h and h != (request.host or "").lower():
                        ref_host = h
                except Exception:
                    ref_host = ""
            from . import analytics_store as an
            an.record(p, ref_host, vid)
        except Exception:
            pass
        return resp

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
        # When payments are live, a paid tier requires an entitlement from a completed
        # checkout. With Stripe unconfigured (preview), this gate is skipped so the demo
        # still generates plans at any tier.
        from . import payments as pay
        if pay.configured() and tier != "free":
            ent = session.get("jb_tier", "free")
            if pay.TIER_RANK.get(ent, 0) < pay.TIER_RANK.get(tier, 0):
                return jsonify({"ok": False, "error": "payment_required", "tier": tier}), 402
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
        soc = (result.get("occupation") or {}).get("soc")
        if soc:
            session["jb_soc"] = soc          # so a later "notify me" / checkout watches this job
        # Off-list careers: when the typed title clearly isn't the matched occupation name,
        # tell the user we scored the closest career we track (keeps the number defensible).
        typed = (profile.title or "").strip()
        occ_title = (result.get("occupation") or {}).get("title", "")
        tl, ol = typed.lower(), occ_title.lower()
        closest_match = occ_title if (typed and tl not in ol and ol not in tl) else None
        return render_template("result.html", r=result, profile=profile,
                               profile_json=json.dumps(asdict(profile)), version=VERSION,
                               closest_match=closest_match, typed_title=typed,
                               licensed=engine.snapshot.licensed)

    @app.get("/jobs")
    def browse_jobs():
        jobs = []
        for o in engine.snapshot.all_occupations():
            jobs.append({
                "soc": o["soc"],
                "title": o["title"],
                "base": round(max(o.get("ai") or 0, o.get("robo") or 0) * 100),
                "wage": o.get("median_wage_national") or 0,
            })
        return render_template("jobs.html", version=VERSION, licensed=engine.snapshot.licensed,
                               families=engine.snapshot.families(), jobs=jobs)

    @app.get("/jobs/<soc>")
    def occupation_page(soc):
        """Programmatic SEO page: a generic read for an occupation (no personal inputs)."""
        occ = engine.snapshot.occupation(soc)
        if occ is None:
            return redirect(url_for("index"))
        prof = Profile(title=occ["title"], country=getattr(g, "country", None))
        result = engine.assess(prof)
        session["jb_soc"] = soc              # so a "notify me" on this page watches this job
        return render_template("result.html", r=result, profile=prof,
                               version=VERSION, licensed=engine.snapshot.licensed, seo=True)

    @app.get("/jobs/<soc>/card.png")
    def occupation_card(soc):
        """Shareable Open Graph score card (PNG) for an occupation."""
        occ = engine.snapshot.occupation(soc)
        if occ is None:
            from flask import abort
            abort(404)
        result = engine.assess(Profile(title=occ["title"]))
        from . import card as card_mod
        from flask import Response
        png = card_mod.render_card(
            occ["title"], result.get("base_exposure", 0),
            ((result.get("timeline") or {}).get("band") or {}).get("label", ""))
        return Response(png, mimetype="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})

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
        # Decorative, data-driven: a glyph per SOC major group, and a short "time in school"
        # hint per O*NET job zone. Both derive from fields already on each career.
        fam_emoji = {"11": "\U0001F4BC", "13": "\U0001F4CA", "15": "\U0001F4BB", "17": "\U0001F3D7",
                     "19": "\U0001F52C", "21": "\U0001F91D", "23": "⚖", "25": "\U0001F393",
                     "27": "\U0001F3A8", "29": "\U0001FA7A", "31": "\U0001F9D1", "33": "\U0001F6E1",
                     "35": "\U0001F373", "37": "\U0001F9F9", "39": "\U0001F487", "41": "\U0001F6D2",
                     "43": "\U0001F5C2", "45": "\U0001F33E", "47": "\U0001F477", "49": "\U0001F527",
                     "51": "\U0001F3ED", "53": "\U0001F69A"}
        school = {1: "Little to none", 2: "High school", 3: "1-2 yrs after HS",
                  4: "~4 yr degree", 5: "Grad school"}
        for c in careers:
            c["emoji"] = fam_emoji.get((c["soc"] or "")[:2], "\U0001F9ED")
            c["school"] = school.get(c.get("job_zone"), "Varies")
        # Side rails stream resilient careers grouped by the schooling they need, each with
        # its AI-safe score, so students can scan "safe options by education level".
        def _rail(zones):
            out = []
            for o in engine.snapshot.all_occupations():
                zone = o.get("job_zone")
                if zone not in zones:
                    continue
                safe = round(100 - max(o.get("ai") or 0, o.get("robo") or 0) * 100)
                if safe < 55:
                    continue
                out.append({"soc": o["soc"], "title": o["title"], "safe": safe,
                            "school": school.get(zone, "Varies")})
            out.sort(key=lambda x: -x["safe"])
            return out[:16]
        rail_early = _rail({2, 3})      # high school / some college or training
        rail_degree = _rail({4, 5})     # bachelor's / graduate
        most, least = _rankings()       # shared full-screen careers browser (same as home)
        return render_template("students.html", version=VERSION, licensed=engine.snapshot.licensed,
                               careers=careers, families=engine.snapshot.families(),
                               sel_field=fam, sel_zone=z, sel_priority=priority,
                               rail_early=rail_early, rail_degree=rail_degree,
                               most_exposed=most, least_exposed=least)

    from . import i18n

    @app.before_request
    def _set_lang():
        from flask import g
        from riskcore import countries
        g.lang = i18n.resolve_locale(request.args.get("lang"),
                                     request.cookies.get("jb_lang"),
                                     request.headers.get("Accept-Language", ""))
        g.country = countries.resolve(request.args.get("country")
                                      or request.cookies.get("jb_country"))

    @app.context_processor
    def _i18n_ctx():
        from flask import g
        from riskcore import countries
        lang = getattr(g, "lang", i18n.DEFAULT)
        country = getattr(g, "country", countries.DEFAULT)
        return {"lang": lang, "langs": i18n.LANGS, "t": i18n.translator(lang),
                "country": country,
                "countries": {c: v["name"] for c, v in countries.COUNTRIES.items()}}

    @app.after_request
    def _persist_lang(resp):
        from riskcore import countries
        chosen = request.args.get("lang")
        if chosen in i18n.LANGS:
            resp.set_cookie("jb_lang", chosen, max_age=31536000, samesite="Lax")
        chosen_c = request.args.get("country")
        if chosen_c and chosen_c.lower() in countries.COUNTRIES:
            resp.set_cookie("jb_country", chosen_c.lower(), max_age=31536000, samesite="Lax")
        return resp

    @app.after_request
    def _attach_ref_cookie(resp):
        # First-touch referral attribution: a friend landing on ?r=<code> is tagged for 30
        # days, so when they later subscribe the checkout carries the referrer (see /checkout).
        try:
            r = request.args.get("r")
            if r and r.isalnum() and len(r) <= 16 and not request.cookies.get("jb_ref"):
                resp.set_cookie("jb_ref", r, max_age=60 * 60 * 24 * 30,
                                httponly=True, samesite="Lax")
        except Exception:
            pass
        return resp

    @app.post("/referral")
    def referral_link():
        from . import referrals
        src = request.get_json(silent=True) or request.form
        email = (src.get("email") or "").strip()
        if not EMAIL_RE.match(email) or len(email) > 254:
            return jsonify({"ok": False, "error": "invalid_email"}), 400
        st = referrals.status(email)
        if not st.get("code"):
            return jsonify({"ok": False, "error": "invalid_email"}), 400
        return jsonify({"ok": True, "link": _canonical_base() + "/?r=" + st["code"],
                        "count": st["count"], "threshold": st["threshold"],
                        "rewarded": st["rewarded"]})

    @app.post("/subscribe")
    def subscribe():
        src = request.get_json(silent=True) or request.form
        email = (src.get("email") or "").strip()
        if not EMAIL_RE.match(email) or len(email) > 254:
            return jsonify({"ok": False, "error": "invalid_email"}), 400
        context = (src.get("context") or "")[:80]
        # Durable, job-tied watch so we can actually alert later. The job is whatever the
        # person is looking at (posted soc, else the last one they assessed this session).
        soc = (src.get("soc") or "").strip() or session.get("jb_soc")
        occ = engine.snapshot.occupation(soc) if soc else None
        try:
            from . import store
            from .alerts import outlook
            exp, dem = outlook(occ) if occ else (None, None)
            store.add_watch(email, occ and soc, source=context or "signup",
                            exposure=exp, demand=dem)
        except Exception as e:  # never let a store hiccup drop the signup
            print(f"[subscribe] store failed: {e}", file=sys.stderr, flush=True)
        # Keep the legacy append log too (harmless belt-and-braces).
        rec = {"email": email, "soc": (soc if occ else None), "context": context,
               "ts": int(time.time())}
        try:
            SIGNUP_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(SIGNUP_FILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
        except Exception:
            pass
        return jsonify({"ok": True})

    # ---- SEO: robots + sitemap. Every occupation is its own landing page, so the
    # sitemap lists them all - that is the organic search engine for the site. ----
    def _canonical_base():
        base = (os.environ.get("JOBCAST_BASE_URL") or request.host_url).rstrip("/")
        # Render terminates TLS upstream, so request.host_url arrives as http://.
        # Search engines want canonical https URLs in robots/sitemap.
        if base.startswith("http://"):
            base = "https://" + base[len("http://"):]
        return base

    @app.get("/robots.txt")
    def robots_txt():
        from flask import Response
        body = ("User-agent: *\n"
                "Allow: /\n"
                "Disallow: /login\n"
                "Disallow: /billing\n"
                "Disallow: /tasks\n"
                "Sitemap: %s/sitemap.xml\n" % _canonical_base())
        return Response(body, mimetype="text/plain")

    @app.get("/sitemap.xml")
    def sitemap_xml():
        from flask import Response
        base = _canonical_base()
        paths = ["/", "/students", "/jobs", "/methodology", "/privacy", "/terms"]
        paths += ["/jobs/" + o["soc"] for o in engine.snapshot.all_occupations()]
        items = "".join(
            "<url><loc>%s%s</loc><changefreq>monthly</changefreq></url>" % (base, p)
            for p in paths)
        xml = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               + items + '</urlset>')
        return Response(xml, mimetype="application/xml")

    # ---- PWA (installable web app; also the base for the Capacitor native wrap) ----
    @app.get("/manifest.webmanifest")
    def manifest():
        from flask import Response
        data = {
            "name": "JobBreak", "short_name": "JobBreak",
            "description": "A clear, sourced read on whether AI or robots are likely to take your job, and when.",
            "start_url": "/", "scope": "/", "display": "standalone",
            "background_color": "#0b1a2e", "theme_color": "#112741",
            "icons": [{"src": "/static/icon.svg", "sizes": "any",
                       "type": "image/svg+xml", "purpose": "any maskable"}],
        }
        return Response(json.dumps(data), mimetype="application/manifest+json")

    @app.get("/sw.js")
    def service_worker():
        from flask import Response
        sw = (
            "const CACHE='jobbreak-v1';"
            "self.addEventListener('install',e=>self.skipWaiting());"
            "self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));"
            "self.addEventListener('fetch',e=>{"
            "const u=new URL(e.request.url);"
            "if(e.request.method!=='GET'||u.origin!==location.origin||!u.pathname.startsWith('/static/'))return;"
            "e.respondWith(caches.open(CACHE).then(c=>c.match(e.request).then(r=>"
            "r||fetch(e.request).then(resp=>{if(resp.ok)c.put(e.request,resp.clone());return resp;}))));"
            "});"
        )
        return Response(sw, mimetype="application/javascript",
                        headers={"Service-Worker-Allowed": "/"})

    # ---- Payments (Stripe hosted Checkout; env-driven, test-mode ready) ----
    @app.post("/checkout")
    def checkout():
        from . import payments as pay
        if not pay.configured():
            return jsonify({"ok": False, "error": "payments_disabled"}), 503
        body = request.get_json(silent=True) or request.form
        tier = (body.get("tier") or "").strip()
        period = (body.get("period") or "monthly").strip()
        if tier not in ("tier1", "tier2", "tier3") or period not in ("monthly", "yearly", "once"):
            return jsonify({"ok": False, "error": "bad_request"}), 400
        base = request.host_url.rstrip("/")
        sess, err = pay.create_checkout_session(
            tier, period,
            success_url=base + "/billing/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=base + "/billing/cancel",
            email=(body.get("email") or None),
            ref=request.cookies.get("jb_ref"))
        if err or not sess:
            return jsonify({"ok": False, "error": err or "stripe_error"}), 400
        return jsonify({"ok": True, "url": sess.url})

    @app.post("/v1/ev")
    def track_event():
        """Record a funnel event (cookie-free, best-effort). Shows in /admin/stats under
        /_ev/<name>, so we can see where people drop in the buy funnel."""
        import re
        body = request.get_json(silent=True) or {}
        name = (body.get("name") or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{1,32}", name or ""):
            return ("", 204)
        try:
            ua = request.headers.get("User-Agent", "")
            if any(b in ua.lower() for b in ("bot", "spider", "crawl", "slurp", "headless",
                                             "python-", "curl", "wget")):
                return ("", 204)
            import hashlib
            xff = request.headers.get("X-Forwarded-For", "")
            ip = (xff.split(",")[0].strip() if xff else (request.remote_addr or ""))
            day = time.strftime("%Y-%m-%d", time.gmtime())
            vid = hashlib.sha256(f"{ip}|{ua}|{day}|{app.secret_key}".encode("utf-8", "ignore")).hexdigest()[:16]
            from . import analytics_store as an
            an.record("/_ev/" + name, "", vid)
        except Exception:
            pass
        return ("", 204)

    @app.get("/billing/success")
    def billing_success():
        from . import payments as pay
        sid = request.args.get("session_id")
        tier = None
        sess = None
        if sid and pay.configured():
            # 1) The webhook may already have recorded this unlock server-side - race-free,
            #    so trust it first and skip the fragile live lookup entirely.
            tier = pay.grant_for(sid)
            # 2) Otherwise the return redirect (especially Apple Pay) can beat Stripe
            #    finalizing the Checkout Session, so the first retrieve may show it
            #    not-yet-complete. Retry briefly so a genuine payment is never shown as
            #    "not confirmed" over a short consistency lag.
            if not tier:
                for _attempt in range(8):
                    sess = pay.retrieve_session(sid)
                    tier = pay.tier_from_session(sess)
                    if tier or sess is None:  # resolved, or a hard retrieve failure
                        break
                    time.sleep(0.5)
            if tier:
                pay.record_grant(sid, tier)  # persist so any later reload unlocks instantly
                session["jb_tier"] = tier
                session.permanent = True
                if sess is None:  # granted from the webhook store; fetch details best-effort
                    sess = pay.retrieve_session(sid)
                details = pay._get(sess, "customer_details") or {}
                email = details.get("email") if hasattr(details, "get") else None
                pay.record_subscription({
                    "email": email,
                    "customer": pay._get(sess, "customer"),
                    "subscription": pay._get(sess, "subscription"),
                    "tier": tier, "ts": int(time.time())})
                # Monitor subscribers are watching the job they were on: arm an alert for it.
                soc = session.get("jb_soc")
                occ = engine.snapshot.occupation(soc) if soc else None
                if email and occ:
                    try:
                        from . import store
                        from .alerts import outlook
                        exp, dem = outlook(occ)
                        store.add_watch(email, soc, source="monitor", exposure=exp, demand=dem)
                    except Exception as e:
                        print(f"[billing] watch failed: {e}", file=sys.stderr, flush=True)
        # A session that exists but didn't resolve to a tier is almost always an async
        # payment still settling - reassure rather than alarm a paid customer. If it is
        # NOT settling, surface the raw session state as a short reference so a stuck
        # payment can be diagnosed from the screen (temporary).
        diag = ""
        if sess is not None and not tier:
            smd = pay._get(sess, "metadata") or {}
            diag = "ref %s/%s/%s" % (
                pay._get(sess, "status") or "-",
                pay._get(sess, "payment_status") or "-",
                (smd.get("tier") if hasattr(smd, "get") else None) or "-")
        # Purchase value for ad-conversion tracking (Meta Pixel / Google Ads), from the
        # Stripe session when present. Best-effort; a missing value just omits the amount.
        paid_value = paid_currency = None
        if tier and sess is not None:
            amt = pay._get(sess, "amount_total")
            if amt:
                paid_value = round(amt / 100.0, 2)
                paid_currency = (pay._get(sess, "currency") or "usd").upper()
        return render_template("billing.html", ok=bool(tier), tier=tier,
                               processing=(not tier and sess is not None), session_id=sid, diag=diag,
                               paid_value=paid_value, paid_currency=paid_currency,
                               version=VERSION, licensed=engine.snapshot.licensed)

    @app.get("/unsubscribe")
    def unsubscribe():
        from . import store
        ok = store.deactivate(request.args.get("t", ""))
        return render_template("billing.html", ok=ok, tier=None, unsubscribed=ok,
                               version=VERSION, licensed=engine.snapshot.licensed)

    @app.post("/tasks/check-alerts")
    @app.get("/tasks/check-alerts")
    def check_alerts_task():
        """Run the outlook-shift check. Protected by JOBCAST_ADMIN_KEY (set it to enable;
        with no key set the endpoint is disabled). Intended for a scheduled trigger."""
        admin_key = os.environ.get("JOBCAST_ADMIN_KEY")
        if not admin_key or request.args.get("key") != admin_key:
            from flask import abort
            abort(404)
        # One-off deliverability test: ?test=you@example.com sends a single email and
        # returns the result, so the live Resend pipeline can be verified without a shell.
        test_to = (request.args.get("test") or "").strip()
        if test_to:
            from . import emailer
            ok, info = emailer.send(
                test_to, "JobBreak test alert",
                "Your JobBreak outlook alerts are working. This is a one-time test; no action needed.",
                "<p>Your <b>JobBreak</b> outlook alerts are working. This is a one-time test; no action needed.</p>")
            return jsonify({"ok": ok, "test_sent_to": test_to, "info": (info or "")[:120]})
        from . import alerts
        dry = request.args.get("dry") == "1"
        summary = alerts.run_check(engine, dry_run=dry)
        return jsonify({"ok": True, "dry_run": dry, **summary})

    @app.get("/billing/cancel")
    def billing_cancel():
        return render_template("billing.html", ok=False, canceled=True,
                               version=VERSION, licensed=engine.snapshot.licensed)

    @app.post("/webhooks/stripe")
    def stripe_webhook():
        from . import payments as pay
        if not pay.configured():
            return ("", 503)
        try:
            event = pay.verify_webhook(request.get_data(), request.headers.get("Stripe-Signature", ""))
        except Exception as e:
            print(f"[payments] webhook verify failed: {e}", file=sys.stderr, flush=True)
            return ("bad signature", 400)
        etype = pay._get(event, "type")
        obj = pay._get(pay._get(event, "data"), "object")
        if etype == "checkout.session.completed":
            md = pay._get(obj, "metadata") or {}
            details = pay._get(obj, "customer_details") or {}
            # Authoritative unlock: this fires server-side and never races the browser
            # redirect, so record the grant here keyed to the checkout session id. The
            # success page reads it first, so access unlocks even if the redirect was slow,
            # lost, or closed before Stripe finished.
            gtier = pay.tier_from_session(obj)
            pay.record_grant(pay._get(obj, "id"), gtier)
            pay.record_subscription({
                "event": etype,
                "email": details.get("email") if hasattr(details, "get") else None,
                "customer": pay._get(obj, "customer"),
                "subscription": pay._get(obj, "subscription"),
                "tier": gtier or (md.get("tier") if hasattr(md, "get") else None),
                "ts": int(time.time())})
            # Referral: a PAID conversion credits the referrer (keyed by the Stripe session
            # id, so a webhook retry never double-counts). At the threshold, issue a one-time
            # reward code and email it. Wrapped so a referral hiccup never fails the webhook.
            ref = md.get("ref") if hasattr(md, "get") else None
            if ref:
                try:
                    from . import referrals
                    referrals.credit(ref, pay._get(obj, "id") or "")
                    if referrals.needs_reward(ref):
                        code, _err = pay.create_reward_promo_code(referrals.REWARD_PERCENT)
                        if code and referrals.mark_rewarded(ref, code):
                            remail = referrals.email_for_code(ref)
                            if remail:
                                from . import emailer
                                emailer.send(
                                    remail,
                                    "You earned 50% off JobBreak Monitor",
                                    "Five friends you referred have subscribed - thank you.\n\n"
                                    "Here is your one-time 50% off code: " + code + "\n\n"
                                    "Enter it at checkout: https://jobbreak.ai\n")
                except Exception as e:
                    print(f"[referral] credit/reward failed: {e}", file=sys.stderr, flush=True)
        return jsonify({"received": True})

    @app.get("/admin/stats")
    def admin_stats():
        """Private traffic dashboard. Protected by JOBCAST_ADMIN_KEY (?key=...); with no
        key set the endpoint is disabled (404)."""
        admin_key = os.environ.get("JOBCAST_ADMIN_KEY")
        if not admin_key or request.args.get("key") != admin_key:
            from flask import abort
            abort(404)
        from . import analytics_store as an
        from . import store as watchstore
        try:
            wc = watchstore.counts()
        except Exception:
            wc = {"active": 0, "job_watches": 0}
        days = request.args.get("days", type=int) or 30
        if days not in (7, 30, 90, 365):
            days = 30
        return render_template("admin_stats.html", s=an.summary(days), watches=wc,
                               key=admin_key, days=days, version=VERSION, noindex=True)

    @app.get("/admin/checkouts")
    def admin_checkouts():
        """Diagnostic: the last few real Stripe Checkout sessions and exactly what the
        grant logic sees for each. Protected by JOBCAST_ADMIN_KEY (?key=...). Plain text so
        it reads on a phone. Temporary - for pinning down a stuck 'processing' payment."""
        admin_key = os.environ.get("JOBCAST_ADMIN_KEY")
        if not admin_key or request.args.get("key") != admin_key:
            from flask import abort
            abort(404)
        from . import payments as pay
        if not pay.configured():
            return Response("stripe not configured\n", mimetype="text/plain")
        lines = []
        try:
            stripe = pay._client()
            sessions = stripe.checkout.Session.list(limit=10, expand=["data.line_items"])
            for s in sessions.auto_paging_iter() if hasattr(sessions, "auto_paging_iter") else sessions.data:
                sid = pay._get(s, "id")
                status = pay._get(s, "status")
                pstatus = pay._get(s, "payment_status")
                mode = pay._get(s, "mode")
                md = pay._get(s, "metadata") or {}
                mtier = md.get("tier") if hasattr(md, "get") else None
                mperiod = md.get("period") if hasattr(md, "get") else None
                created = pay._get(s, "created")
                when = time.strftime("%Y-%m-%d %H:%M", time.gmtime(created)) if created else "-"
                grants = pay.tier_from_session(s)
                lines.append(
                    "%s  %s  mode=%s  status=%s  payment=%s  md.tier=%s  md.period=%s  GRANTS=%s" % (
                        when, (sid or "-")[:24], mode or "-", status or "-", pstatus or "-",
                        mtier or "-", mperiod or "-", grants or "NONE"))
                if len(lines) >= 10:
                    break
        except Exception as e:
            lines.append("ERROR %s: %s" % (type(e).__name__, e))
        return Response(("\n".join(lines) or "no sessions") + "\n", mimetype="text/plain")

    @app.get("/privacy")
    def privacy():
        return render_template("privacy.html", version=VERSION, licensed=engine.snapshot.licensed)

    @app.get("/terms")
    def terms():
        return render_template("terms.html", version=VERSION, licensed=engine.snapshot.licensed)

    @app.get("/methodology")
    def methodology():
        return render_template("methodology.html", version=VERSION,
                               sources=engine.snapshot.data.get("sources") or engine.sources.get("sources", []),
                               snapshot_id=engine.snapshot.snapshot_id,
                               calibration=getattr(engine, "calibration", None),
                               licensed=engine.snapshot.licensed)

    return app


app = create_app()
