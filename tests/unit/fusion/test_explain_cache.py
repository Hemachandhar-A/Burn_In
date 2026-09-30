"""Block 4c Part 2b: fusion.pipeline.run_full_pipeline's per-run ExplainCache (explain/cache.py)
must never change any explanation number - only how many times fit_mcd/fit_ecod/TreeExplainer are
computed. `_explain_cache` is a keyword-only, underscore-prefixed test hook (not part of the public
Part 5.7 signature) letting this file compare the cached (default, real) and uncached (pre-
optimization) code paths on the same lot. Also proves the cache is per-run, local state - two lots
processed in the same process never share it."""
from contracts import ScreeningConfig
from fusion.pipeline import run_full_pipeline
from generator.lot import generate_lot
from harness.golden import golden_lot


def test_golden_lot_part_explanations_identical_with_and_without_the_explain_cache():
    lot = golden_lot()
    config = ScreeningConfig()

    with_cache = run_full_pipeline(lot, config, _explain_cache=True)
    without_cache = run_full_pipeline(lot, config, _explain_cache=False)

    assert set(with_cache.part_explanations) == set(without_cache.part_explanations)
    for cid in with_cache.part_explanations:
        assert with_cache.part_explanations[cid].model_dump() == without_cache.part_explanations[cid].model_dump()

    # The rest of AnalysisResults is untouched by this change too - full equality, belt and braces.
    assert with_cache.model_dump() == without_cache.model_dump()


def test_two_lots_processed_in_the_same_process_do_not_share_explain_cache_state():
    """The cache is built fresh inside run_full_pipeline (a local variable), never module-level -
    running a structurally different lot first must not change a second lot's own results."""
    config = ScreeningConfig()
    golden = golden_lot()

    lot_a = generate_lot("CACHE-ISOLATION-A", "PN-CACHE-ISO", seed=7, account_id="a")

    # Lot B run in isolation (nothing else has run in this process before it).
    baseline = run_full_pipeline(golden, config)

    # Lot A runs first, then lot B (golden) again - lot B's result must be byte-for-byte the same.
    run_full_pipeline(lot_a.dataset, config)
    after_lot_a = run_full_pipeline(golden, config)

    assert after_lot_a.model_dump() == baseline.model_dump()
