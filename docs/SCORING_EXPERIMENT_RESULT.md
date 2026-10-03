# Module A scoring experiment: result (session S6X)

Pre-registered in `docs/SCORING_EXPERIMENT_PLAN.md` (commit a2d23fc, deviations D1-D5 recorded before any variant ran).
All numbers are from `docs/evidence_data/scoring/` (`SUMMARY.md` is the generated table set; `criteria.json` the S1-S5
verdicts) on SYNTHETIC data. Nothing is wired into `fusion/`; the default benchmark output is byte-identical (checked
before and after, see the session report). Machine: Windows 11, Python 3.11.17, uv 0.12.22.

## Verdict

**Variant V1 (absolute, assumption-based calibration, max combination) passes S1 to S5.** No other Stage-A or Stage-B
variant that is not equivalent to it does. The reference-calibrated variants (V2 with K = 5 and 10 earlier lots) fail, and
today's rank-percentile scoring (V0) fails.

This is evidence on synthetic lots whose healthy noise is Gaussian-like by construction. It is a justification to build the
switch and test it on real data, not a claim that real parts behave this way.

## The variant table (held-out evaluation side, REVIEW, thresholds tuned on the separate tuning side)

| variant | P1 clean-lot flag rate | flag rate | recall | cost / part [95% CI] | S1 | S2 | S3 | S4 | S5 | all |
|---|---|---|---|---|---|---|---|---|---|---|
| V0 today, shipped thresholds | 0.186 | 0.183 | 0.741 | 0.301 [0.280, 0.322] | n/a | n/a | n/a | n/a | n/a | (reference row) |
| V0 re-tuned (control) | 0.343 | 0.335 | 0.918 | 0.329 [0.320, 0.338] | FAIL (P1) | PASS | FAIL | FAIL | PASS | FAIL |
| **V1 absolute, max** | **0.048** | 0.099 | 0.913 | **0.096 [0.089, 0.104]** | PASS | PASS | PASS | PASS | PASS | **PASS** |
| V1-C1 mean | 0.074 | 0.117 | 0.907 | 0.119 [0.111, 0.127] | FAIL (P1) | PASS | PASS | PASS | PASS | FAIL |
| V1-C2 hybrid | 0.021 | 0.073 | 0.881 | 0.093 [0.084, 0.101] | PASS | PASS | PASS | PASS | PASS | PASS (tie with V1, see below) |
| V2 K=2 | = V1 (154 reference parts < N_min 300, so always the V1 fallback) | | | | | | | | | PASS |
| V2 K=5 (max) | 0.345 | 0.328 | 0.923 | 0.319 [0.311, 0.327] | FAIL (P1) | PASS | FAIL | FAIL | PASS | FAIL |
| V2 K=10 (max) | 0.323 | 0.305 | 0.911 | 0.304 [0.295, 0.313] | FAIL (P1) | PASS | FAIL | FAIL | PASS | FAIL |

Baselines on the same parts: dynamic PAT cost 0.273 (recall 0.572), fixed delta 0.150 (recall 1.000, precision 0.298),
static PAT 0.475, static limits 0.601. At 1% prevalence, thresholds fixed: V1 0.048, static limits 0.090, dynamic PAT 0.029
(dynamic PAT flags 0.7% of parts and recalls 0.70; V1 flags 4.9% and recalls 0.93).

S4: V1 0.048 vs static limits 0.090 at 1% prevalence (V0: 0.338). S5: V1 is cheaper than V0 in every family (worst difference
-0.189). S6 (leave-one-family-out thresholds, informational): V1 recall 0.909, cost 0.097, all pass.

Selection: V1 and V1-C2 both pass and their costs differ by 0.004 (< the 0.005 tie band), so the simpler V1 is selected.
Stage A: V1 (V2 K=2 is V1 by the cold-start rule; K=5, 10 fail). Stage B: C0 (V1 itself).

## What the numbers say about the original hypothesis

Confirmed by measurement, not assumed. With the clean (zero-defect) lots, V0 at its shipped REVIEW threshold flags 18.6% of
parts, and at the threshold re-tuned on the tuning side it flags 34.3%: the cost-optimal rank threshold lands in the middle
of every lot's top slice because a rank percentile carries no information about whether a lot is clean. Of the three
alternatives only the absolute one removes the floor (clean-lot flag rate 4.8%, held-out flag rate 9.9% against roughly 5-6%
true defect prevalence).

## Why V1 works, and its real-life failure mode

* Mechanism. V1 turns each detector's score into a probability under "healthy parts are Gaussian around the lot median":
  a normal tail for the robust z, a chi-square tail (3 dimensions) for the MCD distance. A clean lot then produces almost no
  small probabilities, and a defective part produces astronomically small ones (the golden part's severity is 55, i.e.
  p ~ 1e-55), so a threshold can separate them. V0 cannot, because it only ever sees ranks.
* The chi-square MCD leg does the work. Post-hoc ablations (exploratory, NOT pre-registered, `exploratory_*.json`): MCD alone
  scores cost 0.0912, z alone 0.1373, V1 without the ECOD leg is identical to V1 (cost 0.0965). The ECOD leg never
  decides a flag under V1: the frozen-anchor conformal p-value saturates near severity 2.6-2.9, below the tuned REVIEW
  threshold 2.956. So V1's ECOD anchor is not needed, and "V1 = z + MCD under a Gaussian assumption" is the honest description.
* Failure mode. It is only as good as the Gaussian assumption. Heavy-tailed healthy noise (the `different_noise_regime`
  family, Student-t) already raises the clean-lot flag rate to 6.7% (above the 5% line for that family; the 4.8% pass is on
  the pooled clean lots, as pre-registered) and doubling the noise (thresholds fixed) raises the flag rate on the baseline family to 0.087 (cost 0.068). A real process with heavier tails, multimodal lots (two fabs or two date codes in one lot) or non-stationary
  readings will produce small p-values for healthy parts. The MCD's chi-square calibration is approximate at 77 parts in 3
  dimensions (the plan's small-sample caveat; not corrected), and the threshold was tuned to this generator's mix of defects.
* Why V2 lost: with a reference of 385-770 parts, a conformal p-value cannot exceed a severity of about 2.6-2.9, and the
  detector's severity is the maximum over 3 detectors x 3 parameters, so a healthy part's smallest p-value is typically
  about 0.1 (severity ~1). Defects and healthy tails are both compressed against that ceiling; the cost-optimal threshold
  (0.99-1.04) then sits inside the healthy distribution and flags about a third of parts, as V0 does. The method forgets
  magnitude beyond the reference range, which is exactly what separates a defect from the worst healthy part.
* V1-C1 (mean) is worse than V1 (P1 fails at 7.4%): averaging does not cancel the heavy-tailed detector, it dilutes the
  signal of the one that sees the defect. V1-C2 (hybrid) is as good as V1 within noise but adds a rule; also its tuned REJECT
  threshold (2.29) is below its REVIEW threshold (3.23) because the two are tuned on different score sets (the override
  already flags the extreme parts), which would need a policy decision before use.

## What real-life data V1 needs

* None beyond the lot itself (lot median and IQR, an MCD fit on the lot's own parts). No history, so a customer's first lot is
  scored the same as the hundredth. That is its main practical advantage over V2.
* What it does assume and that needs a real sample: a threshold. The numbers 2.956 (REVIEW) and 3.419 (REJECT) are tuned on
  synthetic labelled data (FN:FP 20:1 and 10:1). On real data, labels will be rare; the cost-sensitive tuner needs confirmed
  outcomes (the app already records dispositions and confirmed outcomes), or the thresholds have to be set as p-value cut-offs
  (p ~ 1e-3 and 4e-4) and disclosed as judgement.
* For V2 (not recommended): earlier lots of the same part number, at least 300 parts (4 lots of 77), better 10 lots; on a first
  lot it falls back to V1.

## What is still unproven on real data

That real healthy parts are near-Gaussian after robust standardisation; that the false-alarm rate of 4.8% (clean lots) and
9.9% (mixed lots) holds on a real process; that the defect archetypes the generator plants resemble real latent defects
(recall 0.91 is a property of the generator's archetypes); that thresholds transfer between lots, testers and part numbers;
and that MCD behaves on real, possibly rank-deficient or discretised data (the golden fixture already shows the MCD distance
is non-monotone when the covariance is singular, plan D3). Single seed per side; the intervals are over lots, not over
generator seeds. The earlier in-sample caveat also applies to the shipped V0 numbers (its thresholds were tuned on the
same lots it is evaluated on), so the comparison here, where V0 is re-tuned on a separate side, is the fairer one.

## Numbers that differ from earlier reports, and why

V0 cost here is 0.301 (shipped thresholds) or 0.329 (re-tuned), not 0.239: this experiment uses five families with 150
fixed-size lots each (a harder mix, including the high-prevalence family), not the archetype-minimum sets of the published
benchmark. The comparisons within this document are on identical lots.

## Adoption steps for a follow-up session (behind a switch; none of this was done)

1. **Switch.** Add a setting (for example `module_a_scoring: rank | absolute`, default `rank`) read by `fusion/pipeline.py`.
2. **Call site.** `fusion/pipeline.py:72` calls `module_a_detect(frames)`. With the switch on:
   `detect(frames, scoring=ScoringConfig(calibration="absolute", combination="max", review_threshold=..., reject_threshold=...))`.
   No `ecod_anchor` is needed (ablation above). Isolation Forest is already inactive live and is ignored by this path.
3. **Thresholds.** The tier cut-offs are on a different scale (-log10 p, unbounded) from `config/harness_thresholds.yaml`
   (rank percentiles in [0, 1]). `contracts.HarnessThresholds` is frozen, so use the Part 6 contract process
   (`CONTRACT_CHANGES.md`) to add a second threshold set, or a separate config file. Regenerate them from the harness
   (`scripts/scoring_experiment.py` tuning step, or a `harness.bakeoff` option) with provenance; values from this run:
   REVIEW 2.9561, REJECT 3.4186.
4. **`combined_severity` meaning changes** from a 0-1 percentile to -log10 p. Consumers to check: `fusion/pipeline.py`
   (only orders by it), `capa/logic.py:282,324` (ordering and a value), `fusion/gate.py` (uses `severity_tier`, unaffected),
   the contract comment in `contracts.py`, `explain/` text, report templates, and the frontend (`frontend/src/api/schema.d.ts`
   example 0.91, `PartDetailScreen.test.tsx`, any 0-1 display or bar). A display scale (for example a capped, normalised
   value) may be needed; this needs a UI decision.
5. **Tests to update or add.** `tests/unit/module_a/test_p33.py` and other tier tests that read the YAML thresholds;
   `tests/unit/fusion/*`; `tests/unit/capa/*`; the harness comparison (`harness/comparison.py` asserts the shipped max
   combination on percentiles) and `harness/results/p18` regeneration; `tests/integration/test_golden_module_a.py` must still
   pass (the golden part scores 55 against REJECT 3.42); keep a rank-mode copy of every test so the default stays covered.
6. **Demo numbers that would change** (all measured under rank scoring today): DEMO-COMPLETE-01 (REJECT, PDA 0.0779, 15
   flagged), DEMO-EARLY-01, the golden lot's reported severity, the demo screenshots (`frontend/scripts/screenshots.ts`),
   `README.md`, `demo_data/README.md`, `docs/PPT_NUMBERS.md` and `docs/EVIDENCE_MEASUREMENTS.md` (flag rate 0.183 -> about 0.10,
   cost, the 1% prevalence comparison). Re-run `scripts.live_benchmark` and `scripts.sensitivity` (branch evidence-measurements)
   with the switch on.
7. **Before enabling for real use:** validate on real lots (clean-lot flag rate, a sample of confirmed defects), re-check the
   Gaussian assumption per parameter (Q-Q plots of robust z on real healthy parts), decide the threshold policy (tuned cost
   vs fixed p-value), and add a disclosure to `docs/DISCLOSURES.md` stating that the absolute calibration assumes
   near-Gaussian healthy parts and that the thresholds were tuned on synthetic data.

## Deviations recorded after the pre-registration

D6 (post-hoc, exploratory): the two ablations above (V1 without the ECOD leg; z only and MCD only) were run after the
results were known, to explain them. They are not part of S1-S5 and no decision rests on them.
