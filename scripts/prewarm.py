"""Warm what makes the first live upload slow (imports, Module B's synthetic models, one pipeline run).

    python -m scripts.prewarm

Prints seconds per step and the total. Writes nothing to the database: the pipeline is called directly on an
in-memory lot, never through storage. Part number(s) match POST /lots/demo (ingestion/router.py: "DEMO-PN").
"""
import sys
import time
from collections.abc import Callable

DEMO_PART_NUMBERS = ("DEMO-PN",)  # the part number POST /lots/demo generates


def _import_heavy_libs() -> None:
    import lightgbm  # noqa: F401
    import mapie  # noqa: F401
    import shap  # noqa: F401


def _synthetic_models() -> None:
    from module_b.predictor import synthetic_models

    for part_number in DEMO_PART_NUMBERS:
        synthetic_models(part_number)


def _tiny_pipeline() -> None:
    from contracts import ScreeningConfig
    from fusion.pipeline import run_full_pipeline
    from generator.lot import generate_lot

    lot = generate_lot("PREWARM-LOT", DEMO_PART_NUMBERS[0], 42, account_id="prewarm").dataset
    run_full_pipeline(lot, ScreeningConfig())


STEPS: tuple[tuple[str, Callable[[], None]], ...] = (
    ("import shap / lightgbm / mapie", _import_heavy_libs),
    ("module_b synthetic_models", _synthetic_models),
    ("one in-memory pipeline run", _tiny_pipeline),
)


def main() -> int:
    total = 0.0
    for name, step in STEPS:
        start = time.perf_counter()
        step()
        elapsed = time.perf_counter() - start
        total += elapsed
        print(f"prewarm: {name:<32} {elapsed:7.2f}s")
    print(f"prewarm: {'total':<32} {total:7.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
