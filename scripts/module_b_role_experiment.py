"""Session I3 Part 1: Module B's role in finished-lot verdicts (docs/MODULE_B_ROLE_EXPERIMENT.md, pre-registered).

    python -m scripts.module_b_role_experiment extract --set validation --seed 7301   # one seed's 5 families x 20 lots -> part file
    python -m scripts.module_b_role_experiment extract --set published                # seed 2026, the 127 published-protocol lots
    python -m scripts.module_b_role_experiment check                                  # offline (a) == fusion.run_full_pipeline on 5 lots
    python -m scripts.module_b_role_experiment report                                 # tables + decision, from the saved part files

Per-part Module A / Module B inputs are extracted ONCE per lot without the explanation stack (the same calls and per-part picks as
fusion/pipeline.py); the four variants' verdicts are then computed offline from the stored fields in one pass.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("docs/evidence_data/module_b_role")
VALIDATION_SEEDS = (7301, 7302, 7303, 7304, 7305)
PUBLISHED_SEED = 2026
LOTS_PER_SEED_FAMILY = 20
ROLES = ("current", "tiered", "advisory", "off")
VARIANT_NAMES = {"current": "(a) current", "tiered": "(b) tiered", "advisory": "(c) advisory", "off": "(d) off"}
SIMPLICITY = ("off", "advisory", "tiered", "current")  # tie order: simpler first
MIN_RECALL, TIE_TOL, PDA = 0.90, 0.005, 0.05


def b_tier(role: str, exceeds, lower_bound_exceeds) -> str:
    """Module B's tier on a COMPLETE lot under `role` (pre-registered table). None (forecast unavailable) is PASS."""
    if role == "current":
        return "REJECT" if exceeds else "PASS"
    if role == "tiered":
        if lower_bound_exceeds:
            return "REJECT"
        return "REVIEW" if exceeds else "PASS"
    return "PASS"  # advisory / off


def fuse(a_tier: str, b: str) -> str:
    """fusion/gate.py's E12 table, unchanged."""
    if a_tier == "REJECT" or b == "REJECT":
        return "REJECT"
    if a_tier == "REVIEW" and b == "REVIEW":
        return "REJECT"
    if a_tier == "REVIEW" or b == "REVIEW":
        return "WATCH"
    return "PASS"


def a_tier_after_gate(a_tier: str, explainable: bool) -> str:
    return "REVIEW" if (a_tier == "REJECT" and not explainable) else a_tier


def extract_lot(dataset, labels: pd.DataFrame) -> pd.DataFrame:
    """One row per component: the worst Module A result and the worst Module B result, as fusion/pipeline.py picks them."""
    from contracts import to_module_b_input
    from features.compute import compute
    from module_a.detect import detect
    from module_a.settings import module_a_scoring_config
    from module_b.predictor import predict

    frames = compute(dataset)
    cfg = module_a_scoring_config()
    a_results = detect(frames) if cfg is None else detect(frames, scoring=cfg)

    def key(r):
        return r.severity_log10p if r.severity_log10p is not None else r.combined_severity

    a_by = {}
    for r in a_results:
        if r.component_id not in a_by or key(r) > key(a_by[r.component_id]):
            a_by[r.component_id] = r
    b_results = predict([to_module_b_input(f) for f in frames]) if frames else []
    b_by, b_sev = {}, {}
    for r in b_results:
        if r.drift_rate is not None and r.safety_slope is not None and r.safety_slope > 0:
            sev = r.drift_rate / r.safety_slope
            if r.component_id not in b_sev or sev > b_sev[r.component_id]:
                b_sev[r.component_id], b_by[r.component_id] = sev, r
    lab = labels.set_index("component_id")["is_defective"]
    rows = []
    for cid in sorted({f.component_id for f in frames}):
        a, b = a_by.get(cid), b_by.get(cid)
        rows.append({
            "lot_id": dataset.lot_id, "component_id": cid, "is_defective": bool(lab.loc[cid]),
            "a_tier": a.severity_tier if a else "PASS", "a_explainable": bool(a.explainable_corroboration) if a else True,
            "a_cap_reason": a.severity_cap_reason if a else None,
            "b_exceeds": None if b is None else b.exceeds_safety_slope,
            "b_lb_exceeds": None if b is None else b.lower_bound_exceeds_safety_slope,
            "b_severity": b_sev.get(cid),
        })
    return pd.DataFrame(rows)


def add_variants(parts: pd.DataFrame) -> pd.DataFrame:
    parts = parts.copy()
    ex = parts["b_exceeds"].map(lambda v: v is True or v == "True" or v == 1.0)
    lb = parts["b_lb_exceeds"].map(lambda v: v is True or v == "True" or v == 1.0)
    at = [a_tier_after_gate(t, bool(e)) for t, e in zip(parts["a_tier"], parts["a_explainable"])]
    for role in ROLES:
        parts[f"verdict_{role}"] = [fuse(a, b_tier(role, bool(e), bool(l))) for a, e, l in zip(at, ex, lb)]
    return parts


def _sets(which: str, seed: int | None):
    from harness.held_out import generate_held_out_sets

    if which == "published":
        return generate_held_out_sets(seed=PUBLISHED_SEED), PUBLISHED_SEED
    return generate_held_out_sets(seed=seed, min_lots=LOTS_PER_SEED_FAMILY, min_per_archetype=1,
                                  lot_id_prefix=f"V{seed}"), seed


def extract(which: str, seed: int | None) -> int:
    from harness.held_out import ground_truth_labels

    OUT.mkdir(parents=True, exist_ok=True)
    tag = "published_2026" if which == "published" else f"validation_{seed}"
    path = OUT / f"parts_{tag}.csv.gz"
    if path.exists():
        print(f"{tag}: already done", flush=True)
        return 0
    sets, used_seed = _sets(which, seed)
    frames, started = [], time.time()
    for family, hset in sets.items():
        for i, lot in enumerate(hset.lots):
            df = extract_lot(lot.dataset, ground_truth_labels(lot))
            df["family"], df["seed"] = family, used_seed
            frames.append(df)
            if i % 10 == 0:
                print(f"{tag}/{family}: lot {i + 1}/{len(hset.lots)} {time.time() - started:.0f}s", flush=True)
    out = pd.concat(frames, ignore_index=True)
    out.to_csv(path, index=False, compression="gzip")
    print(f"{tag}: {len(out)} parts, {out['lot_id'].nunique()} lots, {time.time() - started:.0f}s", flush=True)
    return 0


def check() -> int:
    """Offline variant (a) == fusion.run_full_pipeline, part for part, on the first lot of each family of seed 7301."""
    from contracts import ScreeningConfig
    from fusion.pipeline import run_full_pipeline
    from harness.held_out import ground_truth_labels

    sets, _ = _sets("validation", 7301)
    bad = total = 0
    for family, hset in sets.items():
        lot = hset.lots[0]
        off = add_variants(extract_lot(lot.dataset, ground_truth_labels(lot))).set_index("component_id")["verdict_current"]
        real = {a.component_id: a.verdict for a in run_full_pipeline(lot.dataset, ScreeningConfig(), _explain_cache=False).assessments}
        mism = [c for c in real if real[c] != off[c]]
        total += len(real)
        bad += len(mism)
        flagged = sum(v != "PASS" for v in real.values())
        print(f"{family:<26} {lot.dataset.lot_id}: parts {len(real)}, flagged {flagged}, mismatches {len(mism)} {mism[:3]}")
    print(f"offline (a) vs pipeline: {total - bad}/{total} identical")
    return 0 if bad == 0 else 1


def _load(files: list[Path]) -> pd.DataFrame:
    return add_variants(pd.concat([pd.read_csv(f) for f in files], ignore_index=True))


def _metrics_table(t: pd.DataFrame, flag_def: str) -> pd.DataFrame:
    from harness import variants as hv

    rows = []
    for role in ROLES:
        col = f"flag_{role}_{flag_def}"
        t[col] = (t[f"verdict_{role}"] != "PASS") if flag_def == "notpass" else (t[f"verdict_{role}"] == "REJECT")
        m = hv.lot_bootstrap_metrics(t, col)
        rows.append({"variant": VARIANT_NAMES[role], "role": role, **m})
    return pd.DataFrame(rows)


def _lot_verdicts(t: pd.DataFrame, role: str) -> pd.Series:
    v = t.groupby("lot_id")[f"verdict_{role}"].agg(
        n="size", rej=lambda s: (s == "REJECT").sum(), watch=lambda s: (s == "WATCH").sum())
    pda = v["rej"] / v["n"]
    return pd.Series(np.where(pda >= PDA, "REJECT", np.where(v["watch"] > 0, "HOLD", "ACCEPT")), index=v.index)


def select(table: pd.DataFrame) -> dict:
    """The pre-registered rule on a validation metrics table (flag = not PASS)."""
    cand = table[table["recall"] >= MIN_RECALL]
    if cand.empty:
        return {"chosen": "current", "adopt": False, "why": "no variant reaches recall 0.90"}
    best = cand["cost_per_part"].min()
    near = cand[cand["cost_per_part"] <= best + TIE_TOL]
    chosen = next(r for r in SIMPLICITY if r in set(near["role"]))
    # The rule's tie-break is on cost within 0.005 of the best; the lowest cost may itself not be the simplest.
    row, cur = table.set_index("role").loc[chosen], table.set_index("role").loc["current"]
    separated = bool(row["cost_per_part_ci_hi"] < cur["cost_per_part_ci_lo"])
    adopt = chosen != "current" and separated
    return {"chosen": chosen, "adopt": adopt, "separated_from_current": separated,
            "candidates": cand["role"].tolist(), "within_tie": near["role"].tolist(),
            "chosen_cost": float(row["cost_per_part"]), "chosen_ci": [float(row["cost_per_part_ci_lo"]), float(row["cost_per_part_ci_hi"])],
            "current_cost": float(cur["cost_per_part"]), "current_ci": [float(cur["cost_per_part_ci_lo"]), float(cur["cost_per_part_ci_hi"])]}


def _show(t: pd.DataFrame, title: str) -> pd.DataFrame:
    pd.set_option("display.width", 250, "display.max_columns", 40)
    cols = ["variant", "n_parts", "n_defective", "n_flagged", "flag_rate", "recall", "recall_ci_lo", "recall_ci_hi",
            "precision", "false_alarms", "missed", "cost_per_part", "cost_per_part_ci_lo", "cost_per_part_ci_hi"]
    print(f"\n== {title}")
    print(t[cols].round(3).to_string(index=False))
    return t


def report() -> int:
    from harness.scoring import expected_cost

    val_files = [OUT / f"parts_validation_{s}.csv.gz" for s in VALIDATION_SEEDS]
    missing = [f for f in val_files if not f.exists()]
    if missing:
        print("missing part files:", [m.name for m in missing], file=sys.stderr)
        return 1
    v = _load(val_files)
    print(f"VALIDATION: {len(v)} parts, {v['lot_id'].nunique()} lots, {int(v['is_defective'].sum())} defective; lots per family:")
    print(v.groupby("family")["lot_id"].nunique().to_string())
    vt = _show(_metrics_table(v, "notpass"), "validation, flagged = not PASS")
    _show(_metrics_table(v, "reject"), "validation, flagged = REJECT only")
    print("\n== validation per-family cost per part (not PASS)")
    pf = {fam: {r: expected_cost(g["is_defective"].to_numpy(bool), (g[f"verdict_{r}"] != "PASS").to_numpy(bool), 10.0)
                for r in ROLES} for fam, g in v.groupby("family", sort=True)}
    print(pd.DataFrame(pf).T.rename(columns=VARIANT_NAMES).round(3).to_string())
    print("\n== validation lot-level verdicts (descriptive)")
    lv = pd.DataFrame({VARIANT_NAMES[r]: _lot_verdicts(v, r).value_counts() for r in ROLES}).fillna(0).astype(int)
    print(lv.to_string())
    dec = select(vt)
    print("\n== DECISION (pre-registered rule, validation only)")
    print(json.dumps(dec, indent=2))
    (OUT / "validation_decision.json").write_text(json.dumps(dec, indent=2), encoding="utf-8")
    vt.drop(columns=[c for c in vt.columns if c.startswith("flag_")]).to_csv(OUT / "validation_table.csv", index=False)

    pub_file = OUT / "parts_published_2026.csv.gz"
    if pub_file.exists():
        p = _load([pub_file])
        print(f"\nPUBLISHED PROTOCOL: {len(p)} parts, {p['lot_id'].nunique()} lots, {int(p['is_defective'].sum())} defective")
        pn = _show(_metrics_table(p, "notpass"), "published protocol (seed 2026), flagged = not PASS")
        pr = _show(_metrics_table(p, "reject"), "published protocol (seed 2026), flagged = REJECT only")
        print("\n== published per-family cost per part (not PASS)")
        pf = {fam: {r: expected_cost(g["is_defective"].to_numpy(bool), (g[f"verdict_{r}"] != "PASS").to_numpy(bool), 10.0)
                    for r in ROLES} for fam, g in p.groupby("family", sort=True)}
        print(pd.DataFrame(pf).T.rename(columns=VARIANT_NAMES).round(3).to_string())
        print("\n== published lot-level verdicts (descriptive)")
        print(pd.DataFrame({VARIANT_NAMES[r]: _lot_verdicts(p, r).value_counts() for r in ROLES}).fillna(0).astype(int).to_string())
        pn.drop(columns=[c for c in pn.columns if c.startswith("flag_")]).to_csv(OUT / "published_table_notpass.csv", index=False)
        pr.drop(columns=[c for c in pr.columns if c.startswith("flag_")]).to_csv(OUT / "published_table_reject.csv", index=False)
        chosen = dec["chosen"]
        only_b = (p["verdict_current"] != "PASS") & (p[f"verdict_{chosen}"] == "PASS")
        print(f"\n== QA visibility (published protocol): parts flagged in (a) and PASS under {chosen}: {int(only_b.sum())} "
              f"({int((only_b & p['is_defective']).sum())} defective, {int((only_b & ~p['is_defective']).sum())} clean)")
        print(f"   of those with Module A tier != PASS: {int((only_b & (p['a_tier'] != 'PASS')).sum())}; with A tier PASS (flagged by B alone): "
              f"{int((only_b & (p['a_tier'] == 'PASS')).sum())}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--set", choices=("validation", "published"), required=True)
    e.add_argument("--seed", type=int)
    sub.add_parser("check")
    sub.add_parser("report")
    a = ap.parse_args(argv)
    if a.cmd == "extract":
        if a.set == "validation" and a.seed not in VALIDATION_SEEDS:
            ap.error(f"--seed must be one of {VALIDATION_SEEDS}")
        return extract(a.set, a.seed)
    return check() if a.cmd == "check" else report()


if __name__ == "__main__":
    sys.exit(main())
