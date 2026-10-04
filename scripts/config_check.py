"""M3 config check: does the harness LIVE path (scoring.run_module_a(..., pooled_reference=False)) give Module A
exactly what the app computes? The app's pipeline (fusion.run_full_pipeline) calls module_a_detect(frames)
with no prior_frames; this runs both on the same complete lots and compares per-part combined_severity and
severity_tier. Measurement only.

    PYTHONPATH=. uv run python -m scripts.config_check [--lots 5] [--out docs/evidence_data/config_check.json]

Criterion (docs/EVIDENCE_PLAN.md, M3): maximum absolute difference below 1e-9.
"""
import argparse
import json
import sys
from pathlib import Path

TOLERANCE = 1e-9


def config_check(n_lots: int = 5, *, seed: int = 2026, n_parts: int | None = None) -> dict:
    from contracts import ScreeningConfig
    from fusion.pipeline import run_full_pipeline
    from generator.families import HELD_OUT_FAMILY_NAMES
    from generator.lot import generate_lot
    from harness import scoring
    from harness.held_out import HeldOutTestSet  # noqa: F401  (documented dependency of the harness path)

    families = [HELD_OUT_FAMILY_NAMES[i % len(HELD_OUT_FAMILY_NAMES)] for i in range(n_lots)]
    lots = [generate_lot(f"CC-{fam}-{i:04d}", "PN-CC", seed, account_id="m1.config_check", family=fam, n_parts=n_parts)
            for i, fam in enumerate(families)]

    # Harness live path: the same function the benchmark uses, on a minimal wrapper exposing .lots.
    class _Set:
        pass
    live = _Set()
    live.lots = lots
    # The same scoring configuration the app resolves (None in rank mode; V1F's ScoringConfig by default).
    from module_a.settings import module_a_scoring_config
    harness_results = {(r.lot_id, r.component_id, r.parameter): r
                       for r in scoring.run_module_a(live, pooled_reference=False, scoring=module_a_scoring_config())}

    compared = 0
    max_abs = 0.0
    tier_mismatches = 0
    per_lot = []
    for lot in lots:
        analysis = run_full_pipeline(lot.dataset, ScreeningConfig())
        lot_max, lot_n = 0.0, 0
        for component_id, app in analysis.module_a_results.items():
            ref = harness_results[(app.lot_id, component_id, app.parameter)]
            diff = abs(app.combined_severity - ref.combined_severity)
            lot_max, lot_n = max(lot_max, diff), lot_n + 1
            tier_mismatches += app.severity_tier != ref.severity_tier
        compared += lot_n
        max_abs = max(max_abs, lot_max)
        per_lot.append({"lot_id": lot.dataset.lot_id, "family": lot.ground_truth.family,
                        "parts_compared": lot_n, "max_abs_diff": lot_max})
    return {"lots": n_lots, "parts_compared": compared, "max_abs_combined_severity_diff": max_abs,
            "severity_tier_mismatches": int(tier_mismatches), "tolerance": TOLERANCE,
            "pass": bool(max_abs < TOLERANCE and tier_mismatches == 0), "per_lot": per_lot}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lots", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path("docs/evidence_data/config_check.json"))
    args = parser.parse_args(argv)
    result = config_check(args.lots)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
