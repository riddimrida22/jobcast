from riskcore import Profile


def test_unknown_title_returns_suggestions(engine):
    r = engine.assess(Profile(title="wizard"))
    assert r["ok"] is False
    assert r["error"] == "occupation_not_found"


def test_data_entry_is_high_ai_exposure(engine):
    r = engine.assess(Profile(title="data entry"))
    assert r["ok"] is True
    assert r["exposure"]["ai_software"] > 60
    assert r["exposure"]["ai_software"] > r["exposure"]["physical_robotics"]
    assert r["base_exposure"] == max(r["exposure"].values())


def test_truck_driver_is_high_robotics_exposure(engine):
    r = engine.assess(Profile(title="truck driver"))
    assert r["exposure"]["physical_robotics"] > r["exposure"]["ai_software"]


def test_scores_within_bounds_for_all_occupations(engine):
    for occ in engine.snapshot.all_occupations():
        r = engine.assess(Profile(title=occ["title"]))
        for v in r["exposure"].values():
            assert 0 <= v <= 100


def test_deterministic(engine):
    p = Profile(title="nurse", zip_code="10001", age=40, experience_years=8)
    assert engine.assess(p) == engine.assess(p)


def test_seniority_reduces_exposure(engine):
    junior = engine.assess(Profile(title="lawyer", experience_years=1))
    senior = engine.assess(Profile(title="lawyer", experience_years=25))
    assert senior["exposure"]["ai_software"] < junior["exposure"]["ai_software"]


def test_union_shifts_timeline_not_score(engine):
    base = engine.assess(Profile(title="truck driver", zip_code="10001"))
    union = engine.assess(Profile(title="truck driver", zip_code="10001", union_status="yes"))
    assert union["exposure"] == base["exposure"]            # score unchanged
    assert union["timeline"]["union_protected"] is True


def test_wage_trajectory_real_terms(engine):
    r = engine.assess(Profile(title="data entry", pay_current=37000, pay_5yr_ago=37000))
    # Flat nominal pay over five years is a real-terms cut once CPI is applied.
    assert r["wages"]["available"] is True
    assert r["wages"]["real_change_pct"] < 0


def test_key_drivers_present_for_exposed_job(engine):
    r = engine.assess(Profile(title="data entry", zip_code="10001"))
    assert len(r["key_drivers"]) >= 1
    assert r["key_drivers"][0]["direction"] in ("raises", "lowers")


def test_adjacency_sorted_and_lower_risk(engine):
    r = engine.assess(Profile(title="data entry"))
    adj = r["adjacent_lower_risk"]
    assert adj, "expected lower-risk adjacent roles"
    maxes = [a["max_exposure"] for a in adj]
    assert maxes == sorted(maxes)
    assert all(m < r["base_exposure"] for m in maxes)


def test_what_if_age_changes_remaining_years(engine):
    p = Profile(title="nurse", age=55)
    w = engine.what_if(p, {"age": 35})
    assert w["ok"] is True
    base_years = w["baseline"]["timeline"]["remaining_working_years"]
    scen_years = w["scenario"]["timeline"]["remaining_working_years"]
    assert scen_years > base_years


def test_what_if_rejects_unknown_field(engine):
    import pytest
    with pytest.raises(ValueError):
        engine.what_if(Profile(title="nurse"), {"gender": "x"})


def test_mitigation_tiers(engine):
    p = Profile(title="data entry")
    assert engine.mitigation_plan(p, "free")["options_count"] == 0
    assert engine.mitigation_plan(p, "tier1")["options_count"] == 1
    t2 = engine.mitigation_plan(p, "tier2")
    assert t2["options_count"] == 3
    assert len(t2["options"]) <= 3
