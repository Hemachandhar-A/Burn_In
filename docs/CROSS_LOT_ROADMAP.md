# Cross-lot detection: what exists, what is missing (read-only investigation, session I2b Part 0e)

Nothing in this file is built. Date: 2026-10-04. All references are to the tree at `adopt-v1f` (base 4013ef7).

## What exists
- **Absolute mode has no isolation-forest leg and does not accept earlier lots.** `module_a/scoring.py` computes z and MCD severities
  (and an ECOD severity only if a reference/anchor is supplied); `isolation_forest_score=None` at `module_a/scoring.py:328`. The doc
  string of `detect()` says a non-rank `scoring` "bypasses the Isolation Forest entirely (prior_frames is ignored)" (`module_a/detect.py:147-149`).
  `ScoringConfig` has `reference` / `ecod_anchor` slots (`module_a/scoring.py:80-81`) that make z/ECOD severities conformal against an
  earlier-lots reference, but nothing in the app fills them.
- **ECOD gives NaN without an anchor** (`module_a/scoring.py:243,255`), so it contributes nothing in the app.
- **Legacy (rank) path:** `detect(frames, prior_frames=...)` builds one IsolationForest per parameter from the pooled earlier-lot frames
  (`module_a/detect.py:175-176`, `_build_if_models`, `:378-398`; fitted with a fixed `random_state`). `prior_frames=None` or `[]` is a cold start: no forest.
  `fusion/pipeline.py:72` never passes `prior_frames`, so the forest is never trained in the live app.
- **Benchmark:** `harness/scoring.py::run_module_a` (`:156-197`) walks a set's lots in order and passes every earlier lot's frames (optionally the
  last K via `max_history`) as `history`, so a set's first lot is a cold start.
- **Stored data that could supply earlier lots:** `storage/repository.py::query_readings_by_part_number(part_number, exclude_lot_id=...)`
  (`:93-121`) re-parses the latest `project_data.raw_data` row of every project with the same part number into `Reading`s.
  `features.compute.build_pooled_reference` (`features/compute.py:30`) already turns such readings into Module B's pooled reference.

## What is missing (minimal reference store)
1. A function turning stored readings of earlier lots into per-parameter `FeatureFrame`s (call `features.compute` per earlier lot) and into a
   `ScoringReference` (sorted z / ECOD / MCD scores per parameter).
2. A call site: `fusion/pipeline.py`, before `module_a_detect`, calling `query_readings_by_part_number(lot.part_number, exclude_lot_id=lot.lot_id)`
   and passing the result as `scoring.reference` (absolute/reference mode) or `prior_frames` (rank mode).
3. A cold-start rule: fewer than `n_min` earlier parts (or fewer than e.g. 3 earlier lots) means no cross-lot leg and a visible note
   "no cross-lot history", never a silent score.
4. Cost per upload: re-parsing every earlier lot's JSON and recomputing features is O(lots x parts x checkpoints); acceptable for tens of lots,
   but caching a per-part-number reference row (rebuilt on save) is the right design beyond that.
5. A leakage guard: the reference must contain earlier lots only (by upload order or date code), never the lot being scored; same-lot parts and
   later lots are excluded.

Estimated effort: 2-3 sessions (reference builder + tests, pipeline wiring + explanation consistency, benchmark with campaign-level drift).

## How to validate
Extend the generator with campaign-level drift (a lot-wide shift that moves all parts of one lot together relative to the part number's history),
run the benchmark in lot order with and without the reference, and compare lot-level detection and clean-lot flag rates; report cost per part with CIs
as in `docs/SYSTEM_LEVEL_BENCHMARK.md`.

## Why the synthetic benchmark cannot show its benefit
The generator has no campaign-level drift: each lot's centre is drawn independently, so earlier lots carry no information about the current
lot's deviation. A lot-wide shift therefore never occurs in the data, and a cross-lot leg can only add noise in the benchmark. Its benefit (catching a
whole lot that drifted together, which a within-lot z-score cannot see by construction) is unmeasured, not disproved.
