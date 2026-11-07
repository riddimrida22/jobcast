# Jobcast - Calibration and Backtest

Offline validation of the exposure model against real BLS employment outcomes. Interpretable statistics only (OLS, ridge-free, cross-validated); the live engine does not use a black-box model. See analysis/calibrate.py.

- Occupations (6-digit SOC): **702**
- Outcome: 5-year national employment change (percent)
- Horizon: 2020-2025 (OEWS May)
- In-sample R2: **0.06**, cross-validated R2: **0.046**

## Does exposure predict employment change? (standardized OLS)

| Feature | Std coef | SE | t | p |
|---|---|---|---|---|
| intercept | 4.933 | 0.963 | 5.12 | 0.0 |
| ai | -0.711 | 1.73 | -0.41 | 0.6813 |
| robo | -1.762 | 1.711 | -1.03 | 0.3034 |
| log_median | 4.591 | 1.078 | 4.26 | 0.0 |
| log_emp0 | 4.454 | 0.989 | 4.5 | 0.0 |

## Correlations with 5-year employment change

| Feature | Pearson r | p | Spearman r |
|---|---|---|---|
| ai | 0.117 | 0.0019 | 0.163 |
| robo | -0.124 | 0.001 | -0.159 |
| log_median | 0.168 | 0.0 | 0.185 |
| log_emp0 | 0.147 | 0.0001 | 0.247 |

## Backtest: employment change by predicted timeline band

If the model is directionally valid, higher-risk bands should show lower employment growth.

| Band | n | Mean emp change % | Median emp change % |
|---|---|---|---|
| Partial, 5 to 10 years | 533 | 6.2 | 5.3 |
| Largely unaffected | 71 | 7.7 | 9.7 |
| Near-term, high | 98 | -3.8 | -6.6 |

## Caveats (read before trusting these numbers)

- The 2020 base year is the COVID shock; employment change partly reflects pandemic recovery, not automation.
- Five years is a short horizon and AI's large labor effects are recent/prospective; weak in-sample signal is expected and honest.
- Employment change is one outcome; wage and hours effects are not modeled here.
