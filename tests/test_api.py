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


def test_green_endpoint_requires_title(client):
    r = client.post("/v1/green", json={"skills": ["x"]})
    assert r.status_code == 400
    assert r.get_json()["error"] == "missing_title"


def test_green_endpoint_accepts_comma_skills(client):
    r = client.post("/v1/green", json={"title": "data entry", "skills": "verify records, reports"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
