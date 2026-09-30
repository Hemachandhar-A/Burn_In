"""Print / save the P1.8 differentiation table for the PPT. A thin wrapper: every number comes from
harness.comparison (E5 step 7); nothing is recomputed or re-tuned here.

    python -m scripts.evaluate [--format table|json|markdown] [--out PATH] [--all] [--seed N]

The default prints the headline table, exactly what `python -m harness.comparison` prints. --all adds the
archetype, matched-flag-budget and golden-example tables. Slow (~minutes): it regenerates the held-out sets.
"""
import argparse
import sys
from pathlib import Path


def build_tables(seed: int, include_all: bool) -> dict:
    from harness import bakeoff
    from harness import comparison as cmp
    from harness.held_out import generate_held_out_sets

    thresholds = bakeoff.load_harness_thresholds()
    parts = cmp.part_table(generate_held_out_sets(seed=seed), thresholds, seed=seed)
    tables = {"headline": cmp.headline_table(parts)}
    if include_all:
        tables["archetype_recall"] = cmp.archetype_recall(parts)
        tables["matched_flag_budget"] = cmp.matched_flag_budget(parts)
        tables["golden_example"] = cmp.golden_example_table(thresholds)
    return tables


def render(tables: dict, fmt: str) -> str:
    if fmt == "json":
        import json
        return json.dumps({k: v.to_dict(orient="records") for k, v in tables.items()}, indent=2)
    if fmt == "markdown":
        from harness.comparison import _md
        return "\n\n".join(f"## {k}\n\n{_md(v)}" for k, v in tables.items()) + "\n"
    return "\n\n".join(v.to_string(index=False) for v in tables.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--format", choices=("table", "json", "markdown"), default="table")
    parser.add_argument("--out", type=Path, default=None, help="also write the output to this file")
    parser.add_argument("--all", action="store_true", help="include archetype, matched-budget and golden tables")
    parser.add_argument("--seed", type=int, default=None, help="default: the harness seed")
    args = parser.parse_args(argv)

    from harness import bakeoff
    text = render(build_tables(args.seed if args.seed is not None else bakeoff.HARNESS_SEED, args.all), args.format)
    print(text)
    if args.out is not None:
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
