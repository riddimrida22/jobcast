# The display scale (headline 0-100)

## Why

The calibrated exposure blend (`riskcore/engine.combined_exposure`, see `CALIBRATION.md`) is
honest but **compressed**: on the live data the most-exposed occupation scores in the low 60s
and most jobs cluster in the 40s-50s. That is faithful to the model (it genuinely cannot push
occupations to the extremes), but it makes the headline number hard to read and nothing reads as
the "near-term, high" the product is about.

## What we do

The headline shown to a person is a **display rescale** of the raw blend: the occupation's
**percentile among all occupations we score**. A displayed 80 means *more exposed than 80% of
occupations*. It is computed in `Engine.display_score` from the sorted distribution of raw blend
values across the snapshot.

Key properties:

- **Monotonic / order-preserving.** The transform never reorders occupations. The ranking - the
  part validated by the backtest (Spearman, AUC, decile lift in `CALIBRATION.md`) - is unchanged.
- **Presentation only.** `combined_exposure` (raw) is unchanged and still drives everything that
  must stay validated: the timeline-band boundaries (`config/weights.json` `timeline_bands`, on the
  raw scale), the green-match selection and its safer/greener margins, adjacency ordering, and the
  convergent-validity / calibration artifacts. Those files are **not** touched by the rescale.
- **Consistent everywhere.** Every surface that shows a headline number applies the same transform
  via `Engine.display_exposure` / `display_score`: the result page, the landing worked example
  (Jane), the "more at risk" / "more resilient" tickers, `/jobs`, the student careers list, the
  green-option payoff, and the outlook-alert baseline. One job never shows two numbers.
- **Bands stay consistent with the number.** A band is assigned on the raw blend against the
  validated thresholds, then shown next to the rescaled number. Because the transform is monotonic,
  a near-term-high job (raw above the top threshold) always displays a high number. Local demand and
  union coverage can still shift the *timeline* band by +/-1 - that reflects *when*, which is
  distinct from the exposure number, and is explained on the methodology page.

## Honesty

The number is framed as a **relative exposure index**, never as a probability. The methodology page
states this plainly ("What the 0 to 100 means"), and the result page labels it "more exposed than
X% of jobs". The honest ranges and caveats from v2 are unchanged.

## If the snapshot changes

The percentile map is rebuilt from the current snapshot's occupation population at engine start, so
the display scale stays correct as the data is refreshed. Nothing to maintain by hand.
