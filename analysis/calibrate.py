"""Calibrate and backtest the exposure model against real BLS employment outcomes.

Question: do occupations we score as more AI/robotics-exposed actually show weaker
employment growth? We regress 5-year employment change (OEWS 2020 -> 2025) on our
exposure scores plus controls, cross-validate out of sample, and check whether higher
predicted-risk bands show lower growth.

Interpretable only: ordinary least squares and ridge in numpy, with p-values from scipy.
No black-box model. The live engine does not use this; it informs the weights and the
honest confidence we report.

HONEST LIMITATION, stated up front and in the report: the 2020 -> 2025 window starts in
the COVID shock, so employment change is noisy and partly reflects pandemic recovery, not
automation. And AI's large labor effects are recent/prospective, so a weak in-sample
relationship is an expected, honest result - we are forecasting future risk, not fitting
the past. Treat this as validation of the plumbing and a baseline, not proof of the score.

Usage (from the repo root):  python -m analysis.calibrate
Writes analysis/calibration.json and CALIBRATION.md.
"""

import json
from pathlib import Path
from typing import Dict, List

import numpy as np
from scipy import stats

from ingest import exposure, oews_files

ROOT = Path(__file__).resolve().parents[1]


def _soc6_exposure() -> Dict[str, Dict[str, float]]:
    """Aggregate O*NET-SOC exposure to 6-digit SOC (mean over detailed codes)."""
    ai = exposure.load_ai()
    robo = exposure.load_robo()
    acc: Dict[str, Dict[str, list]] = {}
    for code, v in ai.items():
        acc.setdefault(code.split("-")[0] + "-" + code.split("-")[1].split(".")[0], {}).setdefault("ai", []).append(v)
    for code, v in robo.items():
        acc.setdefault(code.split("-")[0] + "-" + code.split("-")[1].split(".")[0], {}).setdefault("robo", []).append(v)
    out = {}
    for soc6, d in acc.items():
        if "ai" in d and "robo" in d:
            out[soc6] = {"ai": float(np.mean(d["ai"])), "robo": float(np.mean(d["robo"]))}
    return out


def build_dataset() -> List[Dict[str, float]]:
    exp = _soc6_exposure()
    nat25 = oews_files.load_national(oews_files.find_file("oesm25nat/national_M2025_dl.xlsx"))
    nat20 = oews_files.load_national(oews_files.find_file("oesm20nat/national_M2020_dl.xlsx"))
    rows = []
    for soc6, e in exp.items():
        a, b = nat25.get(soc6), nat20.get(soc6)
        if not a or not b:
            continue
        if not (a["emp"] and b["emp"] and a["median"] and a["emp"] > 0 and b["emp"] > 0):
            continue
        rows.append({
            "soc6": soc6,
            "ai": e["ai"], "robo": e["robo"],
            "log_median": float(np.log(a["median"])),
            "log_emp0": float(np.log(b["emp"])),
            "emp_change_pct": (a["emp"] / b["emp"] - 1.0) * 100.0,
        })
    return rows


def _standardize(M: np.ndarray):
    mu, sd = M.mean(axis=0), M.std(axis=0)
    sd[sd == 0] = 1.0
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


def cv_r2(X: np.ndarray, y: np.ndarray, folds: int = 5, seed: int = 0) -> float:
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(y))
    parts = np.array_split(idx, folds)
    y_true, y_pred = [], []
    for i in range(folds):
        test = parts[i]
        train = np.concatenate([parts[j] for j in range(folds) if j != i])
        beta, *_ = np.linalg.lstsq(X[train], y[train], rcond=None)
        y_pred.append(X[test] @ beta)
        y_true.append(y[test])
    yt, yp = np.concatenate(y_true), np.concatenate(y_pred)
    return float(1 - ((yt - yp) ** 2).sum() / (((yt - yt.mean()) ** 2).sum()))


def band_of(base_exposure: float, bands) -> str:
    for b in bands:
        if base_exposure <= b["max_exposure"]:
            return b["label"]
    return bands[-1]["label"]


def run() -> Dict:
    rows = build_dataset()
    n = len(rows)
    feat_names = ["ai", "robo", "log_median", "log_emp0"]
    X_raw = np.array([[r[f] for f in feat_names] for r in rows])
    y = np.array([r["emp_change_pct"] for r in rows])
    Xz, _, _ = _standardize(X_raw)
    X = np.column_stack([np.ones(n), Xz])

    beta, se, t, p, r2 = ols(X, y)
    cv = cv_r2(X, y)

    # Simple correlations with the outcome.
    corr = {}
    for i, f in enumerate(feat_names):
        pr = stats.pearsonr(X_raw[:, i], y)
        sp = stats.spearmanr(X_raw[:, i], y)
        corr[f] = {"pearson_r": round(float(pr.statistic), 3), "pearson_p": round(float(pr.pvalue), 4),
                   "spearman_r": round(float(sp.statistic), 3)}

    # Backtest the timeline bands: does higher predicted risk show lower employment growth?
    with open(ROOT / "config" / "weights.json", encoding="utf-8") as fh:
        bands = json.load(fh)["timeline_bands"]
    band_stats: Dict[str, Dict] = {}
    for r in rows:
        base = max(r["ai"], r["robo"]) * 100
        lab = band_of(base, bands)
        band_stats.setdefault(lab, {"emp_change": []})["emp_change"].append(r["emp_change_pct"])
    band_summary = {lab: {"n": len(d["emp_change"]),
                          "mean_emp_change_pct": round(float(np.mean(d["emp_change"])), 1),
                          "median_emp_change_pct": round(float(np.median(d["emp_change"])), 1)}
                    for lab, d in band_stats.items()}

    coeffs = [{"feature": ("intercept" if i == 0 else feat_names[i - 1]),
               "std_coef": round(float(beta[i]), 3), "se": round(float(se[i]), 3),
               "t": round(float(t[i]), 2), "p": round(float(p[i]), 4)}
              for i in range(len(beta))]

    return {"n_occupations": n, "horizon": "2020-2025 (OEWS May)",
            "outcome": "5-year national employment change (percent)",
            "r2_in_sample": round(float(r2), 3), "r2_cross_validated": round(cv, 3),
            "coefficients_standardized": coeffs, "correlations": corr,
            "timeline_band_backtest": band_summary,
            "caveats": [
                "The 2020 base year is the COVID shock; employment change partly reflects pandemic recovery, not automation.",
                "Five years is a short horizon and AI's large labor effects are recent/prospective; weak in-sample signal is expected and honest.",
                "Employment change is one outcome; wage and hours effects are not modeled here.",
            ]}


def write_report(res: Dict) -> None:
    (ROOT / "analysis" / "calibration.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    lines = []
    lines.append("# Jobcast - Calibration and Backtest\n")
    lines.append("Offline validation of the exposure model against real BLS employment outcomes. "
                 "Interpretable statistics only (OLS, ridge-free, cross-validated); the live engine "
                 "does not use a black-box model. See analysis/calibrate.py.\n")
    lines.append(f"- Occupations (6-digit SOC): **{res['n_occupations']}**")
    lines.append(f"- Outcome: {res['outcome']}")
    lines.append(f"- Horizon: {res['horizon']}")
    lines.append(f"- In-sample R2: **{res['r2_in_sample']}**, cross-validated R2: **{res['r2_cross_validated']}**\n")

    lines.append("## Does exposure predict employment change? (standardized OLS)\n")
    lines.append("| Feature | Std coef | SE | t | p |")
    lines.append("|---|---|---|---|---|")
    for c in res["coefficients_standardized"]:
        lines.append(f"| {c['feature']} | {c['std_coef']} | {c['se']} | {c['t']} | {c['p']} |")
    lines.append("")

    lines.append("## Correlations with 5-year employment change\n")
    lines.append("| Feature | Pearson r | p | Spearman r |")
    lines.append("|---|---|---|---|")
    for f, c in res["correlations"].items():
        lines.append(f"| {f} | {c['pearson_r']} | {c['pearson_p']} | {c['spearman_r']} |")
    lines.append("")

    lines.append("## Backtest: employment change by predicted timeline band\n")
    lines.append("If the model is directionally valid, higher-risk bands should show lower employment growth.\n")
    lines.append("| Band | n | Mean emp change % | Median emp change % |")
    lines.append("|---|---|---|---|")
    for lab, d in res["timeline_band_backtest"].items():
        lines.append(f"| {lab} | {d['n']} | {d['mean_emp_change_pct']} | {d['median_emp_change_pct']} |")
    lines.append("")

    lines.append("## Caveats (read before trusting these numbers)\n")
    for c in res["caveats"]:
        lines.append(f"- {c}")
    lines.append("")
    (ROOT / "CALIBRATION.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    res = run()
    write_report(res)
    print(json.dumps({k: res[k] for k in ("n_occupations", "r2_in_sample",
                                          "r2_cross_validated")}, indent=2))
    print("correlations:", json.dumps(res["correlations"]))
    print("bands:", json.dumps(res["timeline_band_backtest"]))
