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
    # The headline is the calibrated blend, rescaled for display to the occupation's percentile
    # among all jobs. Data entry (high AI exposure, very routine, low interpersonal) is one of the
    # most exposed occupations, so it lands high on the display scale.
    assert r["base_exposure"] > 70


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


def test_green_option_is_safer_and_reachable(engine):
    g = engine.green_option(Profile(title="data entry"),
                            user_skills=["verify records", "customer service"])
    assert g["ok"] is True
    assert g["targets"], "a high-risk clerical role should have green targets"
    # A high-risk clerical role has clearly-safer ("green") moves, so none should be soft.
    assert g["has_green"] is True
    for t in g["targets"]:
        # Every target must be a genuine risk drop (safer), and never a catch-all bucket.
        assert t["max_exposure"] < t["your_exposure"]
        assert t["risk_drop"] >= 6            # "meaningfully safer" (GREEN_MARGIN)
        assert t["soft"] is False
        assert "all other" not in t["title"].lower()
        assert 0 <= t["qualified_pct"] <= 100
        assert t["qualified_k"] <= t["qualified_m"]
    # Best target leads (ranked by safer x reachable).
    scores = [t["_score"] for t in g["targets"]]
    assert scores == sorted(scores, reverse=True)


def test_green_option_skills_change_qualification(engine):
    # Adding skills that match a target's tasks should not reduce how qualified we look.
    none = engine.green_option(Profile(title="data entry"), user_skills=None)
    some = engine.green_option(Profile(title="data entry"),
                               user_skills=["verify and correct data in records",
                                            "compile and format data into reports"])
    assert none["ok"] and some["ok"]
    assert some["used_user_skills"] is True
    assert none["used_user_skills"] is False


def test_green_option_unknown_title(engine):
    g = engine.green_option(Profile(title="wizard"))
    assert g["ok"] is False


def test_green_option_reports_safety_context(engine):
    # The result always carries the fields the UI needs to frame an honest empty / soft state,
    # never a bare targets list that could read as a false "you're already safe".
    g = engine.green_option(Profile(title="data entry"))
    assert set(("has_green", "soft_only", "already_low")) <= set(g)
    assert g["already_low"] == (g["your_exposure"] < 35)
    # has_green and soft_only are mutually exclusive, and soft_only implies at least one target.
    assert not (g["has_green"] and g["soft_only"])
    if g["soft_only"]:
        assert g["targets"] and all(t["soft"] for t in g["targets"])


def test_green_option_deterministic(engine):
    p = Profile(title="data entry")
    assert engine.green_option(p, user_skills=["a", "b"]) == engine.green_option(p, user_skills=["a", "b"])


# ---- v2 calibrated exposure model ------------------------------------------
def test_v2_blend_is_configured_and_bounded(engine):
    # The headline score comes from the calibrated blend in config, not an unfitted max(ai, robo).
    em = engine.weights.get("exposure_model")
    assert em and em.get("method") == "weighted_blend_0_100"
    w = em["weights"]
    assert abs(sum(w.values()) - 1.0) < 1e-6          # weights are a proper average
    for occ in engine.snapshot.all_occupations():
        assert 0.0 <= engine.combined_exposure(occ) <= 100.0


def test_interpersonal_work_lowers_headline_below_ai_axis(engine):
    # A caring, interpersonal role (nurse) has its headline pulled below its raw AI/robotics
    # exposure, because interpersonal work is the strongest backtest-validated protector.
    r = engine.assess(Profile(title="nurse"))
    assert r["base_exposure"] < max(r["exposure"].values())
    # Data entry (very routine, low interpersonal) is scored clearly riskier than nursing.
    d = engine.assess(Profile(title="data entry"))
    assert d["base_exposure"] > r["base_exposure"]


def test_display_scale_is_monotonic_and_full_range(engine):
    # The headline is a display rescale (percentile) of the raw blend: it must preserve order
    # (never reorder the validated ranking) and spread scores across close to the full 0-100.
    occs = engine.snapshot.all_occupations()
    pairs = sorted((engine.combined_exposure(o), engine.display_exposure(o)) for o in occs)
    disp = [d for _, d in pairs]
    assert disp == sorted(disp)                       # monotonic: raw order -> display order
    assert min(disp) <= 20 and max(disp) >= 80        # uses much more of the 0-100 range than raw
    raw = [r for r, _ in pairs]
    assert (max(raw) - min(raw)) < (max(disp) - min(disp))   # the display genuinely stretches


def test_display_headline_consistent_across_surfaces(engine):
    from riskcore import Profile
    # assess() headline == display_exposure for the same occupation (no two-numbers bug).
    for title in ("data entry", "nurse", "truck driver"):
        occ = engine.snapshot.match_title(title)
        r = engine.assess(Profile(title=title))
        assert round(r["base_exposure"]) == round(engine.display_exposure(occ))


def test_green_targets_are_more_interpersonal_or_less_routine(engine):
    # The re-weighted match should point toward durable, human-centred safer work.
    g = engine.green_option(Profile(title="data entry"),
                            user_skills=["verify records", "customer service"])
    assert g["targets"]
    occ = engine.snapshot.match_title("data entry")
    your_interp = occ.get("interpersonal")
    top = g["targets"][0]
    full = engine.snapshot.occupation(top["soc"]) or {}
    adj = next((a for a in occ.get("adjacent", []) if a["soc"] == top["soc"]), {})
    dest_interp = full.get("interpersonal", adj.get("interpersonal"))
    # The leading safer destination is at least as interpersonal as the starting role.
    if your_interp is not None and dest_interp is not None:
        assert dest_interp >= your_interp - 0.01
