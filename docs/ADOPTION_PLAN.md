# Module A absolute scoring (V1): pre-registration for the evidence gate (session I2a)

Written and committed BEFORE the published-protocol run (Part 3a), the per-family table (3b), the sensitivity sweep (Part 4)
and the heavy-tail check (4b) were run. Nothing below is changed after those runs; a deviation is appended at the end with
its date and reason, never edited in place.

Machine: Windows 11, Python 3.11.17 (uv), Node 22.21.1. Code under test: branch `scoring-adoption`, commit of the switch
(`module_a/settings.py`, `fusion/pipeline.py`), on top of `demo-v1.2` (e1c249b).

## What is measured

**Configurations compared.** (a) "current": rank-percentile scoring with the shipped thresholds (`config/harness_thresholds.yaml`,
REVIEW 0.9556, REJECT 0.9643); (b) "absolute": V1 (`ScoringConfig(calibration="absolute", combination="max")`), severity
s = -log10 p, thresholds fixed at REVIEW 2.956 and REJECT 3.419 (tuning seed 6101, `module_a/settings.py`), no re-tuning on any
data used here. Both are run in the **live configuration** for Module A (no pooled reference, Isolation Forest inactive),
because that is what the app runs and what V1 uses. Part 3a additionally prints the published-configuration current-scoring row
(Isolation Forest active, `harness/results/p18/comparison.md`) so the reader can see both.

**Published protocol (3a/3b).** The same held-out families, seed 2026 and lot counts as `harness/results/p18`
(5 families, 9779 parts, 521 defective), through `harness.held_out.generate_held_out_sets(seed=2026)`. Baselines: static limits,
fixed delta, static PAT, dynamic PAT (`harness.comparison`, unchanged). Bootstrap 95% CI over lots (1000 resamples, fixed seed).
Reported per method: n_flagged, flag_rate, recall, precision, false alarms, missed, cost per part at REVIEW and at REJECT
(FN:FP 10:1, the project's locked ratio). Per held-out family: cost, recall and flag rate, absolute vs current.

**Machinery.** `harness/variants.py` (`run_module_a(scoring=...)`), `harness/comparison.py`, `harness/scoring.py`; a new script
`scripts/adoption_evidence.py` only wires them together (no change to existing defaults).

## Decision rule, fixed now (Part 3c)

ADOPT-READY if ALL hold on the published protocol, live configuration, thresholds fixed:

* **R1** cost per part at REVIEW <= 0.22 (absolute scoring).
* **R2** recall at REVIEW >= 0.75 (absolute scoring).
* **R3** no held-out family's cost per part (REVIEW) is more than 0.03 higher under absolute than under current scoring.
* **R4** clean-lot flag rate THROUGH THE APP (`fusion.run_full_pipeline`, `MODULE_A_SCORING=absolute`) <= 5% at lot sizes >= 30
  (30, 77, 150; 20 clean lots each; baseline family with defect prevalence 0; seed 7101). Measured by
  `tests/integration/test_adoption_absolute.py`.

Otherwise NOT ADOPT-READY, and the failing rule(s) are named.

## Sensitivity sweep with V1 (Part 4a)

`scripts/sensitivity.py` settings, unchanged: noise x0.5 / x1 / x2; prevalence 1% / 3% / 8%; drift-exponent range
lower / baseline / higher; lot size 30 / 77 / 150; 150 lots per setting; live configuration; thresholds fixed (the V1 ones for
absolute). Resumable, one result file per setting under `docs/evidence_data/adoption/sensitivity/`. The earlier sweep for current
scoring is in `docs/evidence_data/sensitivity/`; its REVIEW flag-rate, recall and cost columns are the comparison.

Claims, each HOLDS or "breaks at: <settings>":

* **C1** Module A (absolute) REVIEW recall exceeds static limits, static PAT and dynamic PAT at every setting.
* **C2** Module A (absolute) cost per part beats static limits at every setting.
* **C5** Module A (absolute) flag rate at 1% prevalence <= 6%.
* **C6** Module A (absolute) flag rate on the clean (or lowest-prevalence) lots at noise x2 <= 8%.
* **C7** At every setting Module A (absolute) cost is no worse than under current scoring by more than 0.03.

(C3 and C4 were not defined for this session and are not reported.)

## Heavy-tailed noise (Part 4b)

The `different_noise_regime` family (Student-t healthy noise): clean-lot flag rate (that family at defect prevalence 0, 150 lots,
seed 7101) and cost (published protocol, family row), absolute vs current. Reported, no pass/fail threshold; it is the known
weak spot of the Gaussian assumption.

## What this plan does not do

* It does not re-tune the thresholds, re-select the variant or change V1's calibration.
* It does not test real data. Everything here is synthetic.
* The experiment's earlier cost figures (docs/SCORING_EXPERIMENT_RESULT.md, a harder family mix) are not comparable with the
  published benchmark; only numbers from the protocol above are compared with each other.
* R4 and the part-level flag share use Module A's own tier (`severity_tier != PASS`), not the fused part verdict.

## Already known before the pre-registration was written (stated so it is not read as a prediction)

The size-77 and size-150 clean-lot shares through the app were measured while building the tests (0.0370 and 0.0243); the size-30
share was 0.2233, i.e. R4 FAILS at size 30 (the MCD chi-square leg flags 0.158 of clean parts at n = 30 by itself, 0.118 at 40, 0.071
at 50, 0.027 at 77; diagnostic `docs/evidence_data/adoption/diag_small_lot_mcd.txt`). The rule above is NOT changed because of that
result. It is therefore already known that the overall verdict cannot be ADOPT-READY unless a decision on small lots is made by
the Lead; the remaining items are measured to give that decision its evidence.
