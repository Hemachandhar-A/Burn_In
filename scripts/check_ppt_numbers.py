"""Prints every number used in docs/PPT_NUMBERS.md, read straight from the committed harness tables
(harness/results/p18/*.csv). Nothing is hard-coded: if a table is regenerated, this output (and the doc) must be
re-checked against it.

    python scripts/check_ppt_numbers.py
"""
from pathlib import Path

import pandas as pd

P18 = Path(__file__).resolve().parents[1] / "harness" / "results" / "p18"


ADOPT = Path(__file__).resolve().parents[1] / "docs" / "evidence_data" / "adoption"


def print_v2() -> None:
    """demo-v2 numbers (absolute scoring V1F): fairness table, system-level benchmark, clean-lot flag by size, sweep verdicts."""
    import json

    fair = pd.read_csv(ADOPT / "v1f" / "fairness_table.csv")
    print("\n[v1f/fairness_table.csv] method | n_flagged | flag_rate | recall [ci] | precision | cost_per_part [ci]")
    for _, r in fair.iterrows():
        tau = f" tau={r.tau:.3f}" if pd.notna(r.tau) else ""
        print(f"{r.method:40s}{tau} {int(r.n_flagged)} {r.flag_rate:.3f} {r.recall:.3f} [{r.recall_ci_lo:.3f}, {r.recall_ci_hi:.3f}] "
              f"{r.precision:.3f} {r.cost_per_part:.3f} [{r.cost_per_part_ci_lo:.3f}, {r.cost_per_part_ci_hi:.3f}]")
    taus = json.loads((ADOPT / "v1f" / "baseline_tuned_thresholds.json").read_text())
    print("cost-tuned cuts (score >= tau; 1.0 = default):", {k: round(v["tau"], 3) for k, v in taus.items()})

    sysd = ADOPT / "system_level"
    head = pd.read_csv(sysd / "system_headline.csv")
    print("\n[system_level/system_headline.csv] method | n_flagged | flag_rate | recall [ci] | precision | false_alarms | missed | cost [ci]")
    for _, r in head.iterrows():
        print(f"{r.method:36s} {int(r.n_flagged)} {r.flag_rate:.3f} {r.recall:.3f} [{r.recall_ci_lo:.3f}, {r.recall_ci_hi:.3f}] "
              f"{r.precision:.3f} {int(r.false_alarms)} {int(r.missed)} {r.cost_per_part:.3f} [{r.cost_per_part_ci_lo:.3f}, {r.cost_per_part_ci_hi:.3f}]")
    fam = pd.read_csv(sysd / "system_per_family.csv")
    print("system cost per part by family:")
    print(fam.pivot(index="family", columns="method", values="cost_per_part").round(3).to_string())
    print("gates:", json.dumps(json.loads((sysd / "system_gates.json").read_text())))

    fr4 = pd.read_csv(ADOPT / "v1f" / "fr4_table.csv")
    print("\n[v1f/fr4_table.csv] clean-lot flag rate by lot size n | flag_rate [ci]")
    for _, r in fr4.iterrows():
        print(f"{int(r.n)} {r.flag_rate:.4f} [{r.ci_lo:.3f}, {r.ci_hi:.3f}]")

    claims = json.loads((ADOPT / "v1f" / "sweep" / "claims__live_absolute.json").read_text())
    print("\n[v1f/sweep/claims__live_absolute.json] sweep verdicts (10 settings)")
    for tier, cl in claims.items():
        if tier.startswith('_'):
            continue
        print(tier, {k.split("_")[0]: v["holds"] for k, v in cl.items()},
              "C5", round(cl["C5_flag_rate_le_6pct_at_1pct_prevalence"]["value"], 3),
              "C6", round(cl["C6_flag_rate_le_8pct_on_clean_lots_at_noise_x2"]["value"], 3))


def main() -> None:
    head = pd.read_csv(P18 / "headline.csv").set_index("method")
    n_parts = int(head["n_parts"].iloc[0])
    n_defective = int(head.loc["fixed_delta", "n_flagged"] - head.loc["fixed_delta", "false_alarms"])  # recall 1.0
    print(f"held-out parts: {n_parts}; defective (fixed_delta catches all: flagged - false_alarms): {n_defective}")
    print("\n[headline.csv] method | flag_rate | recall | precision | cost_per_part | n_flagged | false_alarms | missed")
    for m, r in head.iterrows():
        print(f"{m:16s} {r.flag_rate:.3f} {r.recall:.3f} {r.precision:.3f} {r.cost_per_part:.3f} "
              f"{int(r.n_flagged)} {int(r.false_alarms)} {int(r.missed)}")

    a = head.loc["module_a_review"]
    print("\n[recall gap, Module A REVIEW minus baseline] (percentage points)")
    for m in ("static_limits", "static_pat", "dynamic_pat"):
        print(f"{m:14s} baseline recall {head.loc[m, 'recall']:.3f} vs Module A {a.recall:.3f}; "
              f"baseline flag_rate {head.loc[m, 'flag_rate']:.3f} vs Module A {a.flag_rate:.3f}; "
              f"baseline precision {head.loc[m, 'precision']:.3f} vs Module A {a.precision:.3f}")

    print("\n[matched_flag_budget.csv] baseline | n_flagged | baseline_recall | module_a_recall | "
          "baseline_precision | module_a_precision")
    for _, r in pd.read_csv(P18 / "matched_flag_budget.csv").iterrows():
        print(f"{r.baseline:14s} {int(r.n_flagged)} {r.baseline_recall:.3f} {r.module_a_recall:.3f} "
              f"{r.baseline_precision:.3f} {r.module_a_precision:.3f}")

    print("\n[archetype_recall.csv] module_a_review vs best baseline per archetype")
    arch = pd.read_csv(P18 / "archetype_recall.csv")
    for t, g in arch.groupby("defect_type"):
        g = g.set_index("method")
        others = g.drop(["module_a_review", "module_a_reject", "fixed_delta"])["recall"]
        print(f"{t:18s} module_a_review {g.loc['module_a_review', 'recall']:.3f}; best of static/PAT/DPAT "
              f"{others.idxmax()} {others.max():.3f}; fixed_delta {g.loc['fixed_delta', 'recall']:.3f}")

    print("\n[combination_bakeoff.csv]")
    for _, r in pd.read_csv(P18 / "combination_bakeoff.csv").iterrows():
        print(f"{r.strategy:17s} mean_held_out_cost {r.mean_held_out_cost:.3f} shipped={r.shipped}")

    print("\n[module_b_summary.csv]")
    for _, r in pd.read_csv(P18 / "module_b_summary.csv").iterrows():
        print(f"{r.horizon}: model beats best physics baseline in {int(r.model_beats_best)}/{int(r.cells)} cells; "
              f"median coverage {r.median_coverage:.3f}; min coverage {r.min_coverage:.3f}")
    mb = pd.read_csv(P18 / "module_b_vs_physics.csv")
    print(f"target coverage: {sorted(mb.target_coverage.unique())}")
    worst = mb.loc[mb.coverage.idxmin()]
    print(f"lowest-coverage cell: {worst.family} / {worst.parameter} / {worst.horizon} = {worst.coverage:.3f}")
    print_v2()


if __name__ == "__main__":
    main()
