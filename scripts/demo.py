"""CLI walkthrough of the demo lot: same generator call as POST /lots/demo, no HTTP, no database writes.

    python -m scripts.demo
"""
import argparse
import sys
import time
import uuid

_SEVERITY_ORDER = {"REJECT": 0, "WATCH": 1, "PASS": 2}
TOP_N = 5


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lot-id", default=None, help="fixed lot id (the demo lot is deterministic given its lot id)")
    args = parser.parse_args(argv)

    from contracts import ScreeningConfig
    from fusion.pipeline import run_full_pipeline
    from generator.lot import generate_lot

    start = time.perf_counter()
    lot_id = args.lot_id or f"demo-{uuid.uuid4().hex[:8]}"
    # Same call as ingestion/router.py load_demo_lot.
    dataset = generate_lot(lot_id=lot_id, part_number="DEMO-PN", seed=42, account_id="demo-cli").dataset
    results = run_full_pipeline(dataset, ScreeningConfig())
    elapsed = time.perf_counter() - start

    disposition = results.disposition
    flagged = sorted((a for a in results.assessments if a.verdict != "PASS"),
                     key=lambda a: (_SEVERITY_ORDER[a.verdict], a.module_a_rank, a.component_id))
    print(f"lot {dataset.lot_id} ({dataset.part_number}, status {dataset.status}, {len(dataset.readings)} readings)")
    print(f"lot verdict: {disposition.verdict}   PDA: {disposition.pda_result}")
    print(f"flagged parts: {len(flagged)} of {len(results.assessments)}")
    print(f"top {min(TOP_N, len(flagged))} flagged:")
    for a in flagged[:TOP_N]:
        print(f"  {a.component_id:<12} {a.verdict:<7} worst parameter: {a.worst_parameter}")
    if flagged:
        top = flagged[0]
        sentence = top.explanation_sentence
        if sentence is None and top.component_id in results.part_explanations:
            sentence = results.part_explanations[top.component_id].explanation_sentence
        print(f"example sentence ({top.component_id}): {sentence or '(none produced)'}")
    print(f"seconds taken: {elapsed:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
