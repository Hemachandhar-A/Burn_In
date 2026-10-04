# Leave-one-family-out transfer test (session I2b Part 6, optional) - synthetic data

For each of the five generator families, the single cut of fixed delta, dynamic PAT and V1F REVIEW was tuned (`harness.scoring.tune_threshold`, FN:FP 10:1) on the
tuning-side parts (seed 6101) of the OTHER four families, then applied to the held-out family's published-protocol parts (seed 2026, live configuration). Code:
`scripts/transfer_test.py` (test: `tests/unit/scripts/test_transfer_test.py`); data: `docs/evidence_data/adoption/transfer/`.

Cost per part [95% CI over lots] on the held-out family, cut tuned without it:

| Held-out family | fixed delta | dynamic PAT | V1F REVIEW |
|---|---|---|---|
| altered correlation | 0.000 [0.000, 0.000] | 0.074 [0.048, 0.103] | 0.062 [0.040, 0.086] |
| baseline | 0.012 [0.000, 0.028] | 0.082 [0.058, 0.110] | 0.068 [0.044, 0.094] |
| different noise regime | 0.155 [0.094, 0.228] | 0.093 [0.068, 0.119] | 0.079 [0.053, 0.106] |
| higher defect prevalence | 0.044 [0.000, 0.110] | 0.293 [0.184, 0.400] | 0.182 [0.087, 0.275] |
| wider drift exponent | 0.014 [0.000, 0.032] | 0.059 [0.042, 0.079] | 0.056 [0.037, 0.078] |
| mean of the five | 0.045 | 0.120 | 0.089 |
| pooled, all 9,779 parts | 0.047 [0.029, 0.070] | 0.098 [0.079, 0.118] | 0.078 [0.062, 0.093] |

Pooled recall: fixed delta 0.979, dynamic PAT 0.889, V1F 0.908.

**What it shows.** Held-out, a fixed delta limit tuned on other families is still the cheapest method on four of the five families and pooled, so the earlier result
(a tuned delta limit costs less than Module A on synthetic data) does not come from tuning on the evaluation family. The one family where the scale-free V1F cut transfers better is the
different noise regime: the delta cut tuned on the other families flags 19.3% of parts there (cost 0.155) while V1F's flags 8.4% (cost 0.079); the intervals overlap, so this is suggestive only.
V1F's cost is at or below dynamic PAT's on every family and pooled (0.078 [0.062, 0.093] against 0.098 [0.079, 0.118]), but every one of those intervals overlaps. V1F does **not** win with non-overlapping
intervals, so nothing from this test is added to the claims.
