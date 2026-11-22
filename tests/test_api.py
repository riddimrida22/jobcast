def test_health(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["app"] == "jobcast"
    assert data["licensed"] is False


def test_suggest(client):
    r = client.get("/v1/suggest?q=nurse")
    assert r.status_code == 200
    titles = [s["title"] for s in r.get_json()["suggestions"]]
    assert any("Nurse" in t for t in titles)


def test_api_assess_ok(client):
    r = client.post("/v1/assess", json={"title": "software developer", "zip": "10001"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_api_assess_unknown(client):
    r = client.post("/v1/assess", json={"title": "wizard"})
    assert r.status_code == 404
    assert r.get_json()["error"] == "occupation_not_found"


def test_api_whatif_deltas(client):
    r = client.post("/v1/whatif", json={"profile": {"title": "nurse", "age": 55},
                                        "overrides": {"age": 35}})
    data = r.get_json()
    assert data["ok"] is True
    assert "deltas" in data


def test_plan_free_by_default(client):
    r = client.post("/v1/plan", json={"title": "data entry"})
    assert r.get_json()["options_count"] == 0


def test_home_page(client):
    r = client.get("/")
    assert r.status_code == 200
    # Assert on a stable structural hook (the landing "type your job" input) rather than
    # headline copy, which gets tuned often and left this test stale before.
    assert b'id="lp-q"' in r.data


def test_home_scores_consistent_with_engine(client):
    # Regression: the "careers more at risk" ticker used max(ai, robo) while the Jane worked
    # example used the v2 calibrated blend, so one job showed two different numbers on one page.
    # Every headline score must now come from engine.combined_exposure, and the page must show it.
    import re
    from riskcore import load_default_engine
    from server import _build_jane, JANE_TITLE
    e = load_default_engine()
    html = client.get("/").get_data(as_text=True)
    jane = _build_jane(e)
    if jane is None:
        return  # role not in this snapshot; nothing to assert
    occ = e.snapshot.match_title(JANE_TITLE)
    assert jane["from_score"] == round(e.combined_exposure(occ))     # one consistent number
    assert jane["to_score"] < jane["from_score"]                    # the move is genuinely safer
    m = re.search(r"scored <b>(\d+)/100", html)
    assert m and int(m.group(1)) == jane["from_score"]              # the page shows that number


def test_jane_payoff_is_safer_and_not_poorer():
    # The flagship worked example must tell a clean 'doom -> safer AND not-poorer' story on the
    # real (demo) snapshot: a high-risk role with a reachable move to a safer, no-pay-cut career
    # and a sensible hero skill. (The dev fixture is too sparse to carry pay on adjacency, so this
    # guards the business properties on the shipped data.)
    import os
    from pathlib import Path
    demo = Path(__file__).resolve().parents[1] / "data" / "demo" / "snapshot.json"
    if not demo.exists():
        import pytest
        pytest.skip("demo snapshot not present")
    prev = os.environ.get("JOBCAST_SNAPSHOT")
    os.environ["JOBCAST_SNAPSHOT"] = str(demo)
    try:
        from riskcore import load_default_engine
        from server import _build_jane
        j = _build_jane(load_default_engine())
    finally:
        if prev is None:
            os.environ.pop("JOBCAST_SNAPSHOT", None)
        else:
            os.environ["JOBCAST_SNAPSHOT"] = prev
    assert j is not None
    assert j["from_score"] >= 50                 # dramatic enough for the flagship
    assert j["to_score"] < j["from_score"]       # genuinely safer
    assert j["to_pay"] >= j["from_pay"]          # not a pay cut
    assert j["hero_skill"]                        # a real, sensible transferable skill


def test_assess_page_renders_result(client):
    r = client.post("/assess", data={"title": "Registered Nurses", "zip": "10001"})
    assert r.status_code == 200
    assert b"Registered Nurses" in r.data
    assert b"What is driving my result" in r.data


def test_browse_and_occupation_pages(client):
    assert client.get("/jobs").status_code == 200
    assert client.get("/jobs/43-9021").status_code == 200
    assert client.get("/methodology").status_code == 200


def test_green_endpoint_returns_targets(client):
    # Billing is unconfigured in tests, so the paid gate is open (preview behaviour).
    r = client.post("/v1/green", json={"title": "data entry",
                                       "skills": ["verify records", "customer service"]})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    assert "your_exposure" in d and "currency" in d
    for t in d.get("targets", []):
        assert t["max_exposure"] < t["your_exposure"]


def test_progressive_profiling_fields_sharpen_result(client):
    """The post-pay 'Sharpen your result' UI re-posts to /v1/assess with the skipped fields and
    redraws from the response, so each field must measurably change the assessment."""
    base = client.post("/v1/assess", json={"title": "Data Entry Keyers"}).get_json()
    assert base["ok"] is True

    # ZIP -> a metro, with local pay and demand (replaces the national averages).
    loc = client.post("/v1/assess", json={"title": "Data Entry Keyers", "zip_code": "10001"}).get_json()
    assert loc["location"]["metro"] != base["location"]["metro"]
    assert loc["wages"]["occupation_median_wage"]

    # Experience -> the seniority shift eases exposure (headline score drops, never rises).
    exp = client.post("/v1/assess",
                      json={"title": "Data Entry Keyers", "experience_years": 25}).get_json()
    assert exp["base_exposure"] < base["base_exposure"]

    # Age -> a concrete count of remaining working years for the timeline.
    age = client.post("/v1/assess", json={"title": "Data Entry Keyers", "age": 40}).get_json()
    assert age["timeline"]["remaining_working_years"] is not None


def test_green_endpoint_requires_title(client):
    r = client.post("/v1/green", json={"skills": ["x"]})
    assert r.status_code == 400
    assert r.get_json()["error"] == "missing_title"


def test_green_endpoint_accepts_comma_skills(client):
    r = client.post("/v1/green", json={"title": "data entry", "skills": "verify records, reports"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
