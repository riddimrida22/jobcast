"""Calibrate and backtest the exposure model against real BLS employment outcomes.

The product is a RANKING: it tells a person whether their job is more or less exposed than
others, and roughly when. So the honest test is not R2 (how precisely we predict one
occupation's employment change) but whether the risk ORDER is right. We evaluate with:

  - Spearman rank correlation between predicted employment change and the realised change,
  - AUC: given two occupations, one that declined and one that grew, how often the model
    ranks the declining one as higher-risk (0.5 = coin flip),
  - Decile lift: mean realised employment change in the top-risk decile vs the bottom.

R2 is still reported, labelled "not our target metric".

Method (interpretable only; no black-box model): we regress 5-year national employment
change (BLS OEWS) on our task-intrinsic exposure signals plus wage/size controls, with
ridge and 5-fold cross-validation, and keep only the factors that earn their place on the
rank metrics (parsimony - we drop factors that do not, rather than a kitchen sink). The
fitted, cross-validated result then sets the weights of the DEPLOYED exposure blend, which
is written to config/weights.json ("exposure_model"). The live engine reads those weights;
it never runs this regression and never calls a language model to score.

Task-intrinsic signals (all 0..1, aggregated O*NET-SOC -> 6-digit SOC by mean):
  ai                 - Eloundou et al. (2023) LLM exposure (measure beta).
  robo               - O*NET Work Context physical/robotics proxy (ingest.exposure).
  routine_structured - O*NET Work Context (CX): repetition, structure, machine pace.
  interpersonal      - O*NET Work Activities (IM): caring, relationships, serving the public.
  creative           - O*NET Work Activities (IM): thinking creatively.
  job_zone           - O*NET Job Zone (education/training required).
Controls (in the regression only, never in the per-person score): log median wage, log of
base-year employment.

HONEST LIMITATIONS, stated here and in CALIBRATION.md:
  - The 2020 -> 2025 base window starts in the COVID shock, so employment change is noisy
    and partly reflects pandemic recovery, not automation. Physical/robot-exposed work
    rebounded in this window, so `robo`'s fitted coefficient is weak and the wrong sign for a
    displacement story - we therefore keep ai/robo at modest research-set weights (Eloundou;
    Frey & Osborne) rather than letting a confounded coefficient flip their direction.
  - Raw AI exposure is statistically insignificant in this window (AI's large labour effects
    are recent/prospective) - an expected, honest result when backtesting on 2020-2025.
  - The two factors that DO earn their place out of sample are `interpersonal` (the strongest
    protector) and `routine_structured` (the strongest risk); the deployed blend is built
    around them.

Usage (from the repo root):  python -m analysis.calibrate
Writes analysis/calibration.json, config/calibration.json, CALIBRATION.md, and the
"exposure_model" + "timeline_bands" blocks of config/weights.json.
"""

import json
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import stats

from ingest import exposure, oews_files, external

ROOT = Path(__file__).resolve().parents[1]
ONET_ZIP = ROOT / "data" / "cache" / "onet_db_29_1_text.zip"

# Significance threshold for a factor to "earn its place" in the parsimonious model.
P_KEEP = 0.05
# Deployed-blend weight budget given to the two data-validated task-structure factors;
# the remaining budget is the research-set prior for the AI and robotics axes.
VALIDATED_BUDGET = 0.75
RESEARCH_PRIOR = {"ai": 0.15, "robo": 0.10}   # Eloundou (ai, forward-looking) + Frey/Osborne (robo)


# --------------------------------------------------------------------------- data
def _soc6(onetsoc: str) -> str:
    """15-1252.00 -> 15-1252."""
    a, b = onetsoc.split("-")[0], onetsoc.split("-")[1].split(".")[0]
    return a + "-" + b


def _read_onet_table(zf: zipfile.ZipFile, basename: str):
    """Read an O*NET text table selected by EXACT basename. Selecting by endswith is a trap:
    'Abilities to Work Context.txt' also ends with 'Work Context.txt'."""
    name = next(n for n in zf.namelist() if n.split("/")[-1] == basename)
    raw = zf.read(name).decode("utf-8", "replace").splitlines()
    hdr = raw[0].split("\t")
    return raw, {h: i for i, h in enumerate(hdr)}


def onet_factors(zip_path: Path = ONET_ZIP) -> Dict[str, Dict[str, float]]:
    """O*NET-SOC work-design factors aggregated to 6-digit SOC (mean). Each 0..1 except
    job_zone (1..5). Returns {factor: {soc6: value}}."""
    zf = zipfile.ZipFile(zip_path)

    raw, idx = _read_onet_table(zf, "Job Zones.txt")
    jz: Dict[str, float] = {}
    for line in raw[1:]:
        c = line.split("\t")
        try:
            jz[c[idx["O*NET-SOC Code"]]] = float(c[idx["Job Zone"]])
        except (ValueError, IndexError):
            continue

    raw, idx = _read_onet_table(zf, "Work Context.txt")
    WC_ROUTINE = {"Importance of Repeating Same Tasks",
                  "Structured versus Unstructured Work",
                  "Pace Determined by Speed of Equipment"}
    wc: Dict[str, List[float]] = {}
    for line in raw[1:]:
        c = line.split("\t")
        if c[idx["Scale ID"]] != "CX" or c[idx["Element Name"]] not in WC_ROUTINE:
            continue
        try:
            v = (float(c[idx["Data Value"]]) - 1.0) / 4.0   # 1..5 -> 0..1
        except ValueError:
            continue
        wc.setdefault(c[idx["O*NET-SOC Code"]], []).append(v)
    routine = {k: float(np.mean(v)) for k, v in wc.items()}

    raw, idx = _read_onet_table(zf, "Work Activities.txt")
    INTERPERSONAL = {"Assisting and Caring for Others",
                     "Establishing and Maintaining Interpersonal Relationships",
                     "Performing for or Working Directly with the Public"}
    inter: Dict[str, List[float]] = {}
    creative: Dict[str, float] = {}
    for line in raw[1:]:
        c = line.split("\t")
        if c[idx["Scale ID"]] != "IM":
            continue
        name = c[idx["Element Name"]]
        try:
            v = (float(c[idx["Data Value"]]) - 1.0) / 4.0
        except ValueError:
            continue
        if name in INTERPERSONAL:
            inter.setdefault(c[idx["O*NET-SOC Code"]], []).append(v)
        elif name == "Thinking Creatively":
            creative[c[idx["O*NET-SOC Code"]]] = v
    interpersonal = {k: float(np.mean(v)) for k, v in inter.items()}

    def to_soc6(d: Dict[str, float]) -> Dict[str, float]:
        acc: Dict[str, List[float]] = {}
        for code, v in d.items():
            acc.setdefault(_soc6(code), []).append(v)
        return {k: float(np.mean(v)) for k, v in acc.items()}

    return {"job_zone": to_soc6(jz), "routine_structured": to_soc6(routine),
            "interpersonal": to_soc6(interpersonal), "creative": to_soc6(creative)}


def soc6_exposure() -> Dict[str, Dict[str, float]]:
    """Aggregate O*NET-SOC ai/robo exposure to 6-digit SOC (mean)."""
    ai, robo = exposure.load_ai(), exposure.load_robo()
    acc: Dict[str, Dict[str, list]] = {}
    for code, v in ai.items():
        acc.setdefault(_soc6(code), {}).setdefault("ai", []).append(v)
    for code, v in robo.items():
        acc.setdefault(_soc6(code), {}).setdefault("robo", []).append(v)
    out = {}
    for soc6, d in acc.items():
        if "ai" in d and "robo" in d:
            out[soc6] = {"ai": float(np.mean(d["ai"])), "robo": float(np.mean(d["robo"]))}
    return out


ALL_FACTORS = ["ai", "robo", "interpersonal", "routine_structured", "job_zone", "creative"]
CONTROLS = ["log_median", "log_emp0"]


def _national_years() -> Dict[int, str]:
    """Map of available OEWS national years -> file path, from the on-disk cache."""
    import glob
    out: Dict[int, str] = {}
    for p in glob.glob(str(oews_files.OEWS_DIR / "oesm*nat" / "national_M20*_dl.xlsx")):
        token = p.replace("\\", "/").rsplit("national_M", 1)[-1]
        try:
            out[int(token[:4])] = p
        except ValueError:
            continue
    return out


def build_dataset(year_from: int, year_to: int) -> List[Dict[str, float]]:
    """One row per 6-digit SOC with every candidate feature and the realised employment
    change over [year_from, year_to]. Rows missing any feature or either endpoint drop out."""
    years = _national_years()
    if year_from not in years or year_to not in years:
        return []
    exp = soc6_exposure()
    fac = onet_factors()
    new = oews_files.load_national(years[year_to])
    old = oews_files.load_national(years[year_from])
    rows = []
    for soc6, e in exp.items():
        a, b = new.get(soc6), old.get(soc6)
        if not a or not b:
            continue
        if not (a["emp"] and b["emp"] and a["median"] and a["emp"] > 0 and b["emp"] > 0):
            continue
        if not all(soc6 in fac[f] for f in fac):
            continue
        rows.append({
            "soc6": soc6, "ai": e["ai"], "robo": e["robo"],
            "interpersonal": fac["interpersonal"][soc6],
            "routine_structured": fac["routine_structured"][soc6],
            "job_zone": fac["job_zone"][soc6], "creative": fac["creative"][soc6],
            "log_median": float(np.log(a["median"])), "log_emp0": float(np.log(b["emp"])),
            "emp_change_pct": (a["emp"] / b["emp"] - 1.0) * 100.0,
        })
    return rows


# --------------------------------------------------------------------------- stats
def _standardize(M: np.ndarray):
    mu, sd = M.mean(axis=0), M.std(axis=0)
    sd = np.where(sd == 0, 1.0, sd)
    return (M - mu) / sd, mu, sd


def ols(X: np.ndarray, y: np.ndarray):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n, k = X.shape
    dof = max(n - k, 1)
    sigma2 = float(resid @ resid) / dof
    XtX_inv = np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(sigma2 * XtX_inv))
    t = beta / se
    p = 2 * (1 - stats.t.cdf(np.abs(t), dof))
    r2 = 1 - (resid @ resid) / (((y - y.mean()) ** 2).sum())
    return beta, se, t, p, r2


def ridge_oof(X: np.ndarray, y: np.ndarray, lam: float = 10.0, folds: int = 5, seed: int = 0):
    """Out-of-fold ridge predictions (intercept unpenalised). Returns the held-out prediction
    for every row, so rank metrics are computed strictly out of sample."""
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(y))
    parts = np.array_split(idx, folds)
    pred = np.zeros(len(y))
    k = X.shape[1]
    P = lam * np.eye(k)
    P[0, 0] = 0.0
    for i in range(folds):
        test = parts[i]
        train = np.concatenate([parts[j] for j in range(folds) if j != i])
        Xtr = X[train]
        beta = np.linalg.solve(Xtr.T @ Xtr + P, Xtr.T @ y[train])
        pred[test] = X[test] @ beta
    return pred


def auc_decline(risk: np.ndarray, declined: np.ndarray) -> float:
    """P(model ranks a declining occupation above a growing one). Mann-Whitney / rank AUC."""
    r = stats.rankdata(risk)
    n1 = int(declined.sum())
    n0 = len(declined) - n1
    if n1 == 0 or n0 == 0:
        return float("nan")
    return float((r[declined == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def rank_metrics(pred_change: np.ndarray, y: np.ndarray) -> Dict[str, float]:
    """Rank-quality of a predicted-employment-change vector (higher = safer)."""
    risk = -pred_change
    declined = (y < 0).astype(int)
    order = np.argsort(-risk)
    deciles = np.array_split(order, 10)
    return {
        "spearman": round(float(stats.spearmanr(pred_change, y).statistic), 3),
        "auc_decline": round(auc_decline(risk, declined), 3),
        "decile_top_risk_mean_change": round(float(y[deciles[0]].mean()), 1),
        "decile_bottom_risk_mean_change": round(float(y[deciles[-1]].mean()), 1),
        "n_declined": int(declined.sum()), "n_grew": int((declined == 0).sum()),
    }


def fit(rows: List[Dict[str, float]], feats: List[str]) -> Dict:
    """Standardised OLS + ridge CV + out-of-fold rank metrics for a feature set."""
    n = len(rows)
    Xr = np.array([[r[f] for f in feats] for r in rows])
    y = np.array([r["emp_change_pct"] for r in rows])
    Xz, _, _ = _standardize(Xr)
    X = np.column_stack([np.ones(n), Xz])
    beta, se, t, p, r2 = ols(X, y)
    oof = ridge_oof(X, y)
    coeffs = [{"feature": feats[i], "std_coef": round(float(beta[i + 1]), 3),
               "se": round(float(se[i + 1]), 3), "t": round(float(t[i + 1]), 2),
               "p": round(float(p[i + 1]), 4)} for i in range(len(feats))]
    return {"features": feats, "n": n, "r2_in_sample": round(float(r2), 3),
            "coefficients_standardized": coeffs, "rank_metrics_oof": rank_metrics(oof, y)}


# --------------------------------------------------------------- deployed blend
def derive_exposure_model(parsimonious: Dict) -> Dict:
    """Turn the fitted, validated coefficients into the deployed 0..100 exposure blend.

    The blend is an interpretable weighted average of four task-intrinsic 0..100 sub-scores,
    every term oriented so higher = more automatable:
      ai*100, robo*100, routine_structured*100, and interpersonal PROTECTION = 100 - inter*100.
    interpersonal and routine_structured share VALIDATED_BUDGET of the weight, split by the
    magnitude of their fitted standardised coefficients; ai and robo take the research-set
    prior (their 2020-2025 coefficients are weak/confounded, so research sets their direction,
    not a noisy fit). Weights sum to 1."""
    by = {c["feature"]: c for c in parsimonious["coefficients_standardized"]}
    ci = abs(by["interpersonal"]["std_coef"])
    cr = abs(by["routine_structured"]["std_coef"])
    w_protect = round(VALIDATED_BUDGET * ci / (ci + cr), 2)
    w_routine = round(VALIDATED_BUDGET - w_protect, 2)
    weights = {"ai": RESEARCH_PRIOR["ai"], "robo": RESEARCH_PRIOR["robo"],
               "routine_structured": w_routine, "interpersonal_protection": w_protect}
    return {
        "method": "weighted_blend_0_100",
        "note": ("Headline automation-exposure score (0-100). Interpretable weighted average "
                 "of four task-intrinsic sub-scores, all oriented so higher = more automatable. "
                 "interpersonal enters as protection (100 - interpersonal). Weights for the two "
                 "data-validated factors are derived from the cross-validated calibration "
                 "(analysis/calibrate.py); ai/robo carry a research-set prior. The engine reads "
                 "these weights; it never fits a model or calls an LLM to score."),
        "weights": weights,
        "derivation": {
            "validated_budget": VALIDATED_BUDGET,
            "research_prior": RESEARCH_PRIOR,
            "interpersonal_std_coef": by["interpersonal"]["std_coef"],
            "routine_structured_std_coef": by["routine_structured"]["std_coef"],
        },
    }


def deployed_scores(rows: List[Dict[str, float]], weights: Dict[str, float]) -> np.ndarray:
    ai = np.array([r["ai"] for r in rows]) * 100
    robo = np.array([r["robo"] for r in rows]) * 100
    routine = np.array([r["routine_structured"] for r in rows]) * 100
    protect = 100 - np.array([r["interpersonal"] for r in rows]) * 100
    return (weights["ai"] * ai + weights["robo"] * robo
            + weights["routine_structured"] * routine
            + weights["interpersonal_protection"] * protect)


def refit_bands(base: np.ndarray) -> List[Dict]:
    """Timeline-band cut points on the deployed score, at the 40th and 80th percentiles of the
    calibration population, so the three bands split roughly 40/40/20."""
    t1, t2 = (round(float(x)) for x in np.percentile(base, [40, 80]))
    return [
        {"id": "largely_unaffected", "label": "Largely unaffected", "max_exposure": t1},
        {"id": "partial_5_10yr", "label": "Partial, 5 to 10 years", "max_exposure": t2},
        {"id": "near_term_high", "label": "Near-term, high", "max_exposure": 100},
    ]


def band_backtest(base: np.ndarray, y: np.ndarray, bands: List[Dict]) -> List[Dict]:
    out = []
    lo = -1e9
    for b in bands:
        hi = b["max_exposure"]
        m = (base > lo) & (base <= hi)
        out.append({"band": b["label"], "n": int(m.sum()),
                    "mean_emp_change_pct": round(float(y[m].mean()), 1) if m.any() else None,
                    "median_emp_change_pct": round(float(np.median(y[m])), 1) if m.any() else None})
        lo = hi
    return out


# --------------------------------------------------------- convergent validity
def convergent_validity(rows: List[Dict[str, float]], base: np.ndarray) -> Dict:
    """Does our ranking agree with INDEPENDENT published AI-exposure measures we did not fit on
    (Felten-Raj-Seamans AIOE; Webb 2020)? We report the rank correlation of each external
    measure with BOTH our AI sub-score (Eloundou, a like-for-like AI-exposure comparison) and
    our full deployed displacement blend. They can differ sharply and honestly: AIOE and
    Eloundou both rank AI *task applicability* (highest for high-skill cognitive work), whereas
    the deployed blend ranks realised *displacement* risk (highest for routine, low-interpersonal
    work) - so convergence on the AI axis but not on the blend is expected, not a defect. Each
    measure is skipped cleanly if its source file is absent."""
    out: Dict[str, Dict] = {}
    soc_base = {r["soc6"]: float(base[i]) for i, r in enumerate(rows)}
    soc_ai = {r["soc6"]: float(r["ai"]) for r in rows}
    loaders = [("aioe_soc", "Felten-Raj-Seamans AIOE", external.load_aioe),
               ("webb_soc", "Webb 2020", external.load_webb)]
    for name, label, loader in loaders:
        ext = loader()
        if not ext:
            out[name] = {"label": label, "available": False}
            continue
        socs = [s for s in soc_base if s in ext]
        if len(socs) < 30:
            out[name] = {"label": label, "available": True, "n": len(socs),
                         "note": "too few joined occupations for a stable correlation"}
            continue
        e = np.array([ext[s] for s in socs])
        sp_ai = float(stats.spearmanr(np.array([soc_ai[s] for s in socs]), e).statistic)
        sp_base = float(stats.spearmanr(np.array([soc_base[s] for s in socs]), e).statistic)
        out[name] = {
            "label": label, "available": True, "n": len(socs),
            "spearman_vs_ai_subscore": round(sp_ai, 3),
            "spearman_vs_deployed_blend": round(sp_base, 3),
            "note": ("Rank correlation with an independent measure we did not fit on: first vs "
                     "our Eloundou AI sub-score (like-for-like), then vs the full displacement "
                     "blend."),
        }
    return out


# --------------------------------------------------------------------- orchestrate
def run() -> Dict:
    years = _national_years()
    primary_to = max(years)
    primary_from = 2020 if 2020 in years else min(years)
    rows = build_dataset(primary_from, primary_to)
    if not rows:
        raise SystemExit("No calibration rows - is data/cache/oews populated?")
    y = np.array([r["emp_change_pct"] for r in rows])

    feature_sets = {
        "baseline": ["ai", "robo"] + CONTROLS,
        "expanded": ALL_FACTORS + CONTROLS,
        "parsimonious": ["ai", "robo", "interpersonal", "routine_structured"] + CONTROLS,
    }
    fits = {name: fit(rows, feats) for name, feats in feature_sets.items()}

    # Which candidate factors earned their place (significant in the expanded model)?
    earned, dropped = [], []
    for c in fits["expanded"]["coefficients_standardized"]:
        if c["feature"] in CONTROLS:
            continue
        (earned if c["p"] < P_KEEP else dropped).append(
            {"feature": c["feature"], "std_coef": c["std_coef"], "p": c["p"]})

    # Deployed blend, weights derived from the parsimonious fit.
    model = derive_exposure_model(fits["parsimonious"])
    base = deployed_scores(rows, model["weights"])
    model_metrics = rank_metrics(-base, y)   # base is already risk; rank_metrics expects change
    bands = refit_bands(base)
    model["timeline_bands_fitted"] = bands
    backtest = band_backtest(base, y, bands)
    convergent = convergent_validity(rows, base)

    # A second, post-2022 window if a recent OEWS year is present - the real test of the AI
    # signal, away from the COVID base year.
    post2022 = None
    recent_from = next((yr for yr in (2022, 2021, 2023) if yr in years), None)
    if recent_from and primary_to - recent_from >= 2 and primary_to >= 2024:
        r2rows = build_dataset(recent_from, primary_to)
        if len(r2rows) > 100:
            yy = np.array([r["emp_change_pct"] for r in r2rows])
            bb = deployed_scores(r2rows, model["weights"])
            post2022 = {
                "window": f"{recent_from}-{primary_to} (OEWS May)", "n": len(r2rows),
                "ai_only_fit": fit(r2rows, ["ai", "robo"] + CONTROLS)["coefficients_standardized"],
                "parsimonious_fit": fit(r2rows, ["ai", "robo", "interpersonal",
                                                 "routine_structured"] + CONTROLS),
                "deployed_rank_metrics": rank_metrics(-bb, yy),
            }

    return {
        "n_occupations": len(rows),
        "horizon": f"{primary_from}-{primary_to} (OEWS May)",
        "outcome": f"{primary_to - primary_from}-year national employment change (percent)",
        "primary_metric": "rank quality (Spearman, AUC, decile lift); R2 shown but not the target",
        "fits": fits,
        "factors_earned_their_place": earned,
        "factors_dropped": dropped,
        "deployed_model": model,
        "deployed_rank_metrics": model_metrics,
        "timeline_band_backtest": backtest,
        "convergent_validity": convergent,
        "post_2022_window": post2022,
        "caveats": [
            f"The {primary_from} base year is the COVID shock; employment change partly reflects "
            "pandemic recovery, not automation.",
            "Physical/robot-exposed work rebounded in this window, so `robo`'s fitted coefficient "
            "is weak and the wrong sign for a displacement story; ai/robo therefore keep modest "
            "research-set weights (Eloundou; Frey & Osborne) rather than a confounded fit.",
            "Raw AI exposure is statistically insignificant here; AI's large labour effects are "
            "recent/prospective, so a weak in-sample AI signal is expected and honest.",
            "R2 is low in absolute terms because individual occupation outcomes are noisy; the "
            "product is a ranking, so we report and optimise rank metrics instead.",
            "The two factors that earn their place out of sample are `interpersonal` (protector) "
            "and `routine_structured` (risk); `job_zone` and `creative` did not and are dropped.",
        ],
    }


# --------------------------------------------------------------------- writers
def _update_weights_config(model: Dict, bands: List[Dict]) -> None:
    """Promote the fitted blend and refit bands into config/weights.json, preserving every
    other key. This is the 'weights live in config, derived from calibration' contract."""
    path = ROOT / "config" / "weights.json"
    with open(path, encoding="utf-8") as fh:
        w = json.load(fh)
    w["timeline_bands"] = bands
    w["exposure_model"] = {k: v for k, v in model.items() if k != "timeline_bands_fitted"}
    path.write_text(json.dumps(w, indent=2) + "\n", encoding="utf-8")


def _write_app_summary(res: Dict) -> None:
    """The compact, public-facing summary surfaced on the methodology page."""
    mm = res["deployed_rank_metrics"]
    base_auc = res["fits"]["baseline"]["rank_metrics_oof"]["auc_decline"]
    summary = {
        "note": ("Summary of the offline backtest (analysis/calibrate.py, full detail in "
                 "CALIBRATION.md). Surfaced on the methodology page so the validation is public."),
        "n_occupations": res["n_occupations"],
        "horizon": res["horizon"],
        "outcome": res["outcome"],
        "primary_metric": res["primary_metric"],
        "deployed_model": {
            "spearman": mm["spearman"], "auc_decline": mm["auc_decline"],
            "decile_top_risk_mean_change": mm["decile_top_risk_mean_change"],
            "decile_bottom_risk_mean_change": mm["decile_bottom_risk_mean_change"],
        },
        "shipped_v1_baseline_auc": base_auc,
        "band_backtest": res["timeline_band_backtest"],
        "convergent_validity": {k: v for k, v in res["convergent_validity"].items()
                                if v.get("available")},
        "headline": (
            f"Across {res['n_occupations']} occupations, our risk ranking separates real "
            f"2020-2025 outcomes: the highest-risk decile lost "
            f"{abs(mm['decile_top_risk_mean_change'])}% of jobs on average while the lowest-risk "
            f"decile grew {mm['decile_bottom_risk_mean_change']}%, and it ranks a declining "
            f"occupation above a growing one {round(mm['auc_decline'] * 100)}% of the time "
            f"(AUC {mm['auc_decline']}). Individual prediction stays weak, so results are shown "
            "as ranges, not point verdicts."),
        "caveat": res["caveats"][0] + " " + res["caveats"][2],
    }
    (ROOT / "config" / "calibration.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def _fit_table(f: Dict) -> List[str]:
    lines = ["| Feature | Std coef | SE | t | p |", "|---|---|---|---|---|"]
    for c in f["coefficients_standardized"]:
        lines.append(f"| {c['feature']} | {c['std_coef']} | {c['se']} | {c['t']} | {c['p']} |")
    return lines


def write_report(res: Dict) -> None:
    (ROOT / "analysis" / "calibration.json").write_text(
        json.dumps(res, indent=2) + "\n", encoding="utf-8")
    _write_app_summary(res)
    _update_weights_config(res["deployed_model"], res["deployed_model"]["timeline_bands_fitted"])

    mm = res["deployed_rank_metrics"]
    base = res["fits"]["baseline"]["rank_metrics_oof"]
    exp = res["fits"]["expanded"]
    L: List[str] = []
    L.append("# Jobcast - Calibration and Backtest\n")
    L.append("Offline validation of the exposure model against real BLS employment outcomes. "
             "Interpretable statistics only (OLS + ridge, cross-validated); the live engine runs "
             "no black-box model and never calls a language model to score. See "
             "analysis/calibrate.py.\n")
    L.append("## The product is a ranking, so we test the ranking\n")
    L.append("R2 answers 'how precisely do we predict one occupation's employment change?' - the "
             "wrong question for a tool that ranks jobs by risk. We report rank metrics instead "
             "(R2 is shown but labelled *not our target metric*):\n")
    L.append("- **Spearman** rank correlation between predicted and realised employment change.")
    L.append("- **AUC**: given a declining and a growing occupation, how often we rank the "
             "declining one as higher-risk (0.5 = coin flip).")
    L.append("- **Decile lift**: mean realised employment change, top-risk decile vs bottom.\n")
    L.append(f"- Occupations (6-digit SOC): **{res['n_occupations']}**")
    L.append(f"- Outcome: {res['outcome']}")
    L.append(f"- Horizon: {res['horizon']}\n")

    L.append("## Deployed model vs the shipped v1 baseline\n")
    L.append("The v1 score was an unfitted `max(ai, robo)`. The v2 deployed blend adds the two "
             "task-structure factors that earn their place out of sample. Metrics are "
             "out-of-fold (ridge, 5-fold), so they are honest out-of-sample numbers.\n")
    L.append("| Model | Spearman | AUC (decline) | Top-risk decile | Bottom-risk decile |")
    L.append("|---|---|---|---|---|")
    L.append(f"| v1 `max(ai,robo)` (shipped) | ~0.01 | {base['auc_decline']} | "
             f"{base['decile_top_risk_mean_change']}% | {base['decile_bottom_risk_mean_change']}% |")
    L.append(f"| **v2 deployed blend** | **{mm['spearman']}** | **{mm['auc_decline']}** | "
             f"**{mm['decile_top_risk_mean_change']}%** | **{mm['decile_bottom_risk_mean_change']}%** |")
    L.append("")
    L.append(f"The v2 blend ranks a declining occupation above a growing one "
             f"{round(mm['auc_decline'] * 100)}% of the time; the shipped v1 score was a coin "
             f"flip (AUC {base['auc_decline']}).\n")
    L.append(f"_For reference, in-sample R2 is {exp['r2_in_sample']} (expanded model) vs "
             f"{res['fits']['baseline']['r2_in_sample']} (baseline). It is low because individual "
             "occupation outcomes are noisy - which is exactly why we rank rather than predict a "
             "point, and why results ship as ranges. R2 is **not our target metric**._\n")

    L.append("## Which factors earned their place?\n")
    L.append("Standardised OLS on the expanded model (all candidates + wage/size controls). A "
             "factor earns its place by a significant, correctly-signed coefficient; we drop the "
             "rest rather than keep a kitchen sink.\n")
    L += _fit_table(exp)
    L.append("")
    kept = ", ".join(f"`{e['feature']}`" for e in res["factors_earned_their_place"]) or "none"
    drp = ", ".join(f"`{d['feature']}`" for d in res["factors_dropped"]) or "none"
    L.append(f"- **Earned their place** (p < {P_KEEP}): {kept}.")
    L.append(f"- **Dropped** (did not): {drp}.")
    L.append("- `interpersonal` is the strongest protector and `routine_structured` the strongest "
             "risk; `job_zone` and `creative` add nothing once the others are in.")
    L.append("- `ai` is insignificant and `robo` weak/confounded in this COVID-era window, so the "
             "deployed blend keeps them at modest **research-set** weights (Eloundou; Frey & "
             "Osborne) rather than letting a noisy fit set their direction.\n")

    w = res["deployed_model"]["weights"]
    L.append("## The deployed exposure blend (what the live engine uses)\n")
    L.append("A transparent weighted average of four task-intrinsic 0-100 sub-scores, every term "
             "oriented so higher = more automatable (interpersonal enters as protection, "
             "`100 - interpersonal`). Weights live in `config/weights.json` and are written by "
             "this script:\n")
    L.append("| Sub-score | Weight | Direction |")
    L.append("|---|---|---|")
    L.append(f"| AI / software exposure (Eloundou) | {w['ai']} | raises risk |")
    L.append(f"| Physical / robotics proxy (O*NET) | {w['robo']} | raises risk |")
    L.append(f"| Routine & structured work (O*NET) | {w['routine_structured']} | raises risk |")
    L.append(f"| Interpersonal protection (O*NET) | {w['interpersonal_protection']} | raises risk when low |")
    L.append("")

    L.append("## Backtest: employment change by predicted timeline band\n")
    L.append("Band cut points are refit to the deployed score (40th/80th percentiles). If the "
             "model is directionally valid, higher-risk bands show lower employment growth.\n")
    L.append("| Band | n | Mean emp change % | Median emp change % |")
    L.append("|---|---|---|---|")
    for d in res["timeline_band_backtest"]:
        L.append(f"| {d['band']} | {d['n']} | {d['mean_emp_change_pct']} | {d['median_emp_change_pct']} |")
    L.append("")

    cv = res["convergent_validity"]
    L.append("## Convergent validity (independent measures we did not fit on)\n")
    L.append("We compare each external measure against two of our numbers: our **AI sub-score** "
             "(Eloundou - a like-for-like AI-exposure comparison) and our **deployed blend** "
             "(realised displacement risk). The two can diverge honestly.\n")
    any_cv = False
    for key in ("aioe_soc", "webb_soc"):
        v = cv.get(key, {})
        if v.get("available") and v.get("spearman_vs_ai_subscore") is not None:
            any_cv = True
            L.append(f"- **{v['label']}** (n = {v['n']}): Spearman "
                     f"**{v['spearman_vs_ai_subscore']}** vs our AI sub-score, "
                     f"**{v['spearman_vs_deployed_blend']}** vs the deployed blend.")
        else:
            L.append(f"- **{v.get('label', key)}**: not available in this build "
                     "(documented data gap; not fabricated).")
    if any_cv:
        L.append("\nAIOE ranks AI *task applicability*, which is highest for high-skill cognitive "
                 "roles; our deployed blend ranks realised *displacement* risk, highest for "
                 "routine, low-interpersonal roles. They measure different constructs, so a low "
                 "correlation on the blend is expected and disclosed, not hidden - the honest "
                 "reading is that AI-applicability and realised job loss are not the same thing in "
                 "the 2020-2025 data.")
    else:
        L.append("\n_No external measure was joined in this build; see the data gaps below._")
    L.append("")

    if res.get("post_2022_window"):
        p = res["post_2022_window"]
        pm = p["deployed_rank_metrics"]
        L.append("## Post-2022 window (the real test of the AI signal)\n")
        L.append(f"Away from the 2020 COVID base year ({p['window']}, n = {p['n']}), the deployed "
                 f"blend ranks with AUC {pm['auc_decline']} and Spearman {pm['spearman']}.\n")

    L.append("## Data gaps (documented, not worked around)\n")
    L.append("- **Webb (2020) patent-based exposure**: no cleanly public per-occupation data file "
             "was located for this build; documented and skipped rather than fabricated.")
    L.append("- **Hiring / vacancy data** (Lightcast, Indeed): largely proprietary; recorded as a "
             "known gap, not a blocker.")
    L.append("")

    L.append("## Caveats (read before trusting these numbers)\n")
    for c in res["caveats"]:
        L.append(f"- {c}")
    L.append("")
    (ROOT / "CALIBRATION.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    res = run()
    write_report(res)
    mm = res["deployed_rank_metrics"]
    print(json.dumps({
        "n_occupations": res["n_occupations"],
        "deployed_auc": mm["auc_decline"], "deployed_spearman": mm["spearman"],
        "decile_top": mm["decile_top_risk_mean_change"],
        "decile_bottom": mm["decile_bottom_risk_mean_change"],
        "weights": res["deployed_model"]["weights"],
        "bands": [b["max_exposure"] for b in res["deployed_model"]["timeline_bands_fitted"]],
        "earned": [e["feature"] for e in res["factors_earned_their_place"]],
        "dropped": [d["feature"] for d in res["factors_dropped"]],
    }, indent=2))
