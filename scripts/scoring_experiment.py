"""S6X: Module A scoring experiment - resumable runner (docs/SCORING_EXPERIMENT_PLAN.md).

    PYTHONPATH=. uv run python -m scripts.scoring_experiment prepare        # generate lots + raw scores (cached)
    PYTHONPATH=. uv run python -m scripts.scoring_experiment stage-a        # V0, V1, V2 k=2/5/10 (C0), then the winner
    PYTHONPATH=. uv run python -m scripts.scoring_experiment stage-b        # C0/C1/C2 on the Stage-A winner
    PYTHONPATH=. uv run python -m scripts.scoring_experiment units         # P3-P5 (+ unit P1/P2) from pytest
    PYTHONPATH=. uv run python -m scripts.scoring_experiment report         # tables, S1-S5 -> SUMMARY.md
    PYTHONPATH=. uv run python -m scripts.scoring_experiment all

Every run writes one small JSON under docs/evidence_data/scoring/ (variant_<name>.json); a finished run is never
repeated. Raw lot data is cached under .evidence_logs/cache (not committed; it is a pure function of the seeds).
Thresholds are tuned on the TUNING side only and stored in each variant's JSON; the evaluation reads them back.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from harness import bakeoff, golden
from harness import comparison as cmp
from harness import variants as hv
from module_a.scoring import ScoringReference, compute_lot_raw, frame_severities

OUT_DIR = Path("docs/evidence_data/scoring")
CACHE_DIR = Path(".evidence_logs/cache")
BASELINE_METHODS = cmp.BASELINES
P1_LIMIT = 0.05
S2_MIN_RECALL, S3_MAX_COST, S5_MAX_EXTRA = 0.75, 0.22, 0.03
TIE = 0.005


@dataclass
class Experiment:
    out_dir: Path = OUT_DIR
    cache_dir: Path = CACHE_DIR
    lots: dict[str, int] = field(default_factory=dict)  # side name -> lots per family override (smoke tests)
    _prep: dict = field(default_factory=dict)

    def n(self, side: str) -> int:
        return self.lots.get(side, hv.SIDES[side].lots_per_family)

    # --- data --------------------------------------------------------------------------------------------------
    def prepared(self, kind: str) -> dict[str, hv.Prepared]:
        """kind: tune | eval | clean (five families) or rob (the three settings)."""
        if kind in self._prep:
            return self._prep[kind]
        out = {}
        t0 = time.time()
        if kind == "rob":
            for key in hv.SETTINGS:
                out[key] = hv.prepare(hv.SIDES["rob"], key, hv.setting_family(key), n_lots=self.n("rob"),
                                      with_baselines=True, cache_dir=self.cache_dir)
        else:
            for key in hv.FAMILY_NAMES:
                family = hv.clean_family(key) if kind == "clean" else hv.setting_family(key)
                out[key] = hv.prepare(hv.SIDES[kind], key, family, n_lots=self.n(kind),
                                      with_baselines=(kind == "eval"), cache_dir=self.cache_dir)
                print(f"  prepared {kind}/{key} ({time.time() - t0:.0f}s)", flush=True)
        self._prep[kind] = out
        return out

    def anchors(self) -> dict[str, ScoringReference]:
        return {k: ScoringReference.from_raw(p.raws[:hv.ANCHOR_LOTS]) for k, p in self.prepared("tune").items()}

    def path(self, name: str) -> Path:
        return self.out_dir / f"{name}.json"

    # --- one variant -------------------------------------------------------------------------------------------
    def run_variant(self, variant: hv.Variant) -> dict:
        path = self.path(f"variant_{variant.name}")
        if path.exists():
            print(f"{variant.name}: already done", flush=True)
            return json.loads(path.read_text(encoding="utf-8"))
        t0 = time.time()
        anchors = self.anchors()
        tune = hv.score_side(self.prepared("tune"), variant, anchors, skip_first=hv.ANCHOR_LOTS)
        thresholds = hv.tune_thresholds(tune)
        lofo = hv.leave_one_family_out_thresholds(tune)
        result = {"variant": variant.name, "calibration": variant.calibration, "combination": variant.combination,
                  "history_lots": variant.history_lots, "thresholds": thresholds, "lofo_thresholds": lofo,
                  "tuning_parts": len(tune), "tuning_defective": int(tune["is_defective"].sum())}

        eval_table = hv.score_side(self.prepared("eval"), variant, anchors)
        result["eval"] = self._operating_points(eval_table, thresholds)
        result["eval_lofo"] = self._lofo_metrics(eval_table, lofo)
        if variant.calibration == "rank":
            shipped = bakeoff.load_harness_thresholds()
            result["eval_shipped_thresholds"] = self._operating_points(
                eval_table, {"review": shipped.module_a_review_threshold, "reject": shipped.module_a_reject_threshold})
            result["shipped_thresholds"] = {"review": shipped.module_a_review_threshold,
                                            "reject": shipped.module_a_reject_threshold}

        clean_table = hv.score_side(self.prepared("clean"), variant, anchors)
        result["p1"] = self._p1(clean_table, thresholds, result.get("shipped_thresholds"))

        rob = {}
        for key, prep in self.prepared("rob").items():
            # the robustness sequences use the baseline family's frozen anchor
            table = hv.score_side({key: prep}, variant, {key: anchors["baseline"]})
            rob[key] = self._operating_points(table, thresholds)
        result["robustness"] = rob
        result["p2"] = self._p2(variant, thresholds, anchors)
        result["seconds"] = round(time.time() - t0)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(hv.jsonable(result), indent=2), encoding="utf-8")
        tmp.replace(path)
        print(f"{variant.name}: done in {result['seconds']}s  review={thresholds['review']:.4g} "
              f"reject={thresholds['reject']:.4g}  eval review cost={result['eval']['review']['cost_per_part']:.4f}",
              flush=True)
        return result

    @staticmethod
    def _operating_points(table: pd.DataFrame, thresholds) -> dict:
        t = hv.apply_thresholds(table, thresholds)
        out = {tier: hv.lot_bootstrap_metrics(t, f"{tier}_flagged") for tier in ("review", "reject")}
        out["per_family_cost_review"] = hv.per_family_cost(t, "review_flagged")
        out["per_family_cost_reject"] = hv.per_family_cost(t, "reject_flagged")
        out["per_family_recall_review"] = {
            fam: float(g.loc[g["is_defective"], "review_flagged"].mean()) if g["is_defective"].any() else None
            for fam, g in t.groupby("family", sort=True)}
        return out

    def _lofo_metrics(self, eval_table: pd.DataFrame, lofo: dict) -> dict:
        parts = []
        for fam, th in lofo.items():
            parts.append(hv.apply_thresholds(eval_table[eval_table["family"] == fam], th))
        t = pd.concat(parts, ignore_index=True)
        return {"review": hv.lot_bootstrap_metrics(t, "review_flagged"),
                "reject": hv.lot_bootstrap_metrics(t, "reject_flagged"),
                "per_family_cost_review": hv.per_family_cost(t, "review_flagged")}

    @staticmethod
    def _p1(clean: pd.DataFrame, thresholds, shipped) -> dict:
        t = hv.apply_thresholds(clean, thresholds)
        out = {"threshold_review": thresholds["review"], "share_flagged_pooled": float(t["review_flagged"].mean()),
               "per_family": {f: float(g["review_flagged"].mean()) for f, g in t.groupby("family", sort=True)},
               "n_parts": len(t)}
        lot_order = {lot: i for i, lot in enumerate(dict.fromkeys(t["lot_id"]))}
        t = t.assign(_i=t["lot_id"].map(lambda x: int(x.rsplit("-", 1)[1])))
        out["share_flagged_lots_10_plus"] = float(t.loc[t["_i"] >= 10, "review_flagged"].mean())
        if shipped:
            s = hv.apply_thresholds(clean, shipped)
            out["share_flagged_at_shipped_thresholds"] = float(s["review_flagged"].mean())
        return out

    def _p2(self, variant: hv.Variant, thresholds, anchors) -> dict:
        """The golden part (GOLDEN-045, 45 uA against a 10 uA lot median): is it at REJECT? Cold start = no history;
        warm = the variant's own history mechanism, fed the last K tuning-side lots of the baseline family."""
        raw = compute_lot_raw(golden.golden_feature_frames())
        tune_raws = self.prepared("tune")["baseline"].raws
        out = {}
        for label, history in (("cold", []), ("warm", tune_raws[-(variant.history_lots or 0):] if variant.history_lots else [])):
            if variant.calibration == "rank":
                score = hv.rank_frame_scores(raw)
                over = None
            else:
                ref = ScoringReference.from_raw(history) if (history and variant.calibration == "reference") else None
                sev = frame_severities(raw, variant.config(reference=ref, anchor=anchors["baseline"]))
                score, over = sev.combined, sev.override
            part = hv._part_level(raw, score, over).set_index("component_id")
            g = part.loc[golden.GOLDEN_COMPONENT_ID]
            rank_top = bool(g["score"] >= part["score"].max())
            out[label] = {"score": float(g["score"]), "is_top": rank_top,
                          "reject": bool(g["score"] >= thresholds["reject"]),
                          "review": bool(g["score"] >= thresholds["review"] or g["override"])}
        out["pass"] = bool(out["cold"]["reject"] and out["warm"]["reject"])
        return out

    # --- baselines (variant independent) -----------------------------------------------------------------------
    def baselines(self) -> dict:
        path = self.path("baselines")
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        out = {}
        for kind in ("eval", "rob"):
            sets = self.prepared(kind)
            tables = []
            for key, prep in sets.items():
                t = prep.labels.merge(prep.baselines, on=["lot_id", "component_id"], how="left", validate="one_to_one")
                t["family"] = key
                tables.append(t)
            table = pd.concat(tables, ignore_index=True)
            groups = {"ALL": table} if kind == "eval" else {k: g for k, g in table.groupby("family")}
            out[kind] = {gname: {m: hv.lot_bootstrap_metrics(g, f"{m}_flagged", judged_col=f"{m}_evaluable")
                                 for m in BASELINE_METHODS} for gname, g in groups.items()}
            if kind == "eval":
                out["eval_per_family_cost"] = {m: hv.per_family_cost(table[table[f"{m}_evaluable"]], f"{m}_flagged")
                                               for m in BASELINE_METHODS}
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.path("baselines").write_text(json.dumps(hv.jsonable(out), indent=2), encoding="utf-8")
        return out


# --- unit-test properties --------------------------------------------------------------------------------------

def run_units(out_dir: Path) -> dict:
    path = out_dir / "unit_properties.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    junit = Path(".evidence_logs/units.xml")
    subprocess.run([sys.executable, "-m", "pytest", "tests/unit/module_a/test_scoring_variants.py", "-q",
                    f"--junitxml={junit}", "-p", "no:cacheprovider"], check=False)
    result: dict[str, dict[str, str]] = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        name = case.get("name", "")
        if "[" not in name:
            continue
        func, variant = name[:-1].split("[", 1)
        prop = func.split("_")[1]  # test_p3_... -> p3
        status = "fail" if case.find("failure") is not None or case.find("error") is not None else "pass"
        result.setdefault(variant, {})[prop] = status
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


# --- decisions ---------------------------------------------------------------------------------------------------

def unit_key(res: dict) -> str:
    """The name of the unit-test parametrisation that covers a variant (V1/V2 x C0/C1/C2); V0 has none."""
    if res["calibration"] == "rank":
        return "V0"
    return f"{'V1' if res['calibration'] == 'absolute' else 'V2'}-C{ {'max': 0, 'mean': 1, 'hybrid': 2}[res['combination']] }"


def criteria(res: dict, v0: dict, static_prev1_cost: float, units: dict) -> dict:
    """S1-S5 (and informational S6) for one variant result."""
    unit = units.get(unit_key(res), {})
    p1 = res["p1"]["share_flagged_pooled"]
    # P3-P5 come from tests/unit/module_a/test_scoring_variants.py; V0 (today's code) has no such test and is
    # reported as not run (None), which does not by itself fail S1.
    s1_parts = {"P1": p1 <= P1_LIMIT, "P2": res["p2"]["pass"],
                **{k: (unit.get(k) == "pass" if unit else None) for k in ("p3", "p4", "p5")}}
    review = res["eval"]["review"]
    cost, recall = review["cost_per_part"], review["recall"]
    prev1_cost = res["robustness"]["prev_1"]["review"]["cost_per_part"]
    v0_fam = v0["eval"]["per_family_cost_review"]
    fam = res["eval"]["per_family_cost_review"]
    worst_extra = max(fam[f] - v0_fam[f] for f in fam)
    out = {"S1": all(v for v in s1_parts.values() if v is not None), "S1_parts": s1_parts, "S2": recall >= S2_MIN_RECALL, "S3": cost <= S3_MAX_COST,
           "S4": prev1_cost <= static_prev1_cost, "S5": worst_extra <= S5_MAX_EXTRA,
           "values": {"P1": p1, "recall": recall, "cost": cost, "prev1_cost": prev1_cost,
                      "static_limits_prev1_cost": static_prev1_cost, "worst_family_extra_cost_vs_v0": worst_extra}}
    out["all"] = all(out[k] for k in ("S1", "S2", "S3", "S4", "S5"))
    lo = res["eval_lofo"]["review"]
    lo_fam = res["eval_lofo"]["per_family_cost_review"]
    out["S6_informational"] = {"recall": lo["recall"], "cost": lo["cost_per_part"],
                               "S2": lo["recall"] >= S2_MIN_RECALL, "S3": lo["cost_per_part"] <= S3_MAX_COST,
                               "S5": max(lo_fam[f] - v0_fam[f] for f in lo_fam) <= S5_MAX_EXTRA}
    return out


def select(results: list[dict], v0: dict, static_prev1_cost: float, units: dict, order: list[str]) -> dict:
    """The pre-registered selection rule: lowest held-out REVIEW cost among variants meeting S1-S5; costs within
    TIE are a tie, and a tie goes to the earlier (simpler) variant in `order`. If none passes, the best that passes
    S1 (else the lowest-cost non-V0), labelled not passing."""
    scored = []
    for r in results:
        c = criteria(r, v0, static_prev1_cost, units)
        scored.append((r["variant"], c, c["values"]["cost"]))
    passing = [s for s in scored if s[1]["all"]]
    pool, label = passing, "passing"
    if not passing:
        s1 = [s for s in scored if s[1]["S1"] and s[0] != "V0"]
        pool, label = (s1, "best_not_passing_S1_only") if s1 else (
            [s for s in scored if s[0] != "V0"], "best_not_passing_no_S1")
    if not pool:
        return {"winner": None, "label": "none", "criteria": {n: c for n, c, _ in scored}}
    best_cost = min(s[2] for s in pool)
    tied = [s for s in pool if s[2] - best_cost < TIE]
    winner = min(tied, key=lambda s: order.index(s[0]))
    return {"winner": winner[0], "label": label, "tied_with": [s[0] for s in tied],
            "criteria": {n: c for n, c, _ in scored}}


def load_variant(exp: Experiment, name: str) -> dict:
    return json.loads(exp.path(f"variant_{name}").read_text(encoding="utf-8"))


def static_prev1(exp: Experiment) -> float:
    return exp.baselines()["rob"]["prev_1"]["static_limits"]["cost_per_part"]


def stage_a(exp: Experiment) -> dict:
    path = exp.path("stage_a_decision")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    variants = hv.stage_a_variants()
    results = [exp.run_variant(v) for v in variants]
    units = run_units(exp.out_dir)
    v0 = next(r for r in results if r["variant"] == "V0")
    # V2k2 is V1 by the cold-start rule (154 < 300 reference parts); keep it in the table, prefer the simpler V1
    order = ["V0", "V1", "V2k2", "V2k10", "V2k5"]
    decision = select(results, v0, static_prev1(exp), units, order)
    path.write_text(json.dumps(hv.jsonable(decision), indent=2), encoding="utf-8")
    print("Stage A winner:", decision["winner"], decision["label"], flush=True)
    return decision


def stage_b(exp: Experiment) -> dict:
    path = exp.path("stage_b_decision")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    a = stage_a(exp)
    base = next((v for v in hv.stage_a_variants() if v.name == a["winner"]), None)
    if base is None or base.calibration == "rank":
        decision = {"applicable": False, "reason": f"Stage-A winner is {a['winner']!r} (rank): only C0 is defined"}
        path.write_text(json.dumps(decision, indent=2), encoding="utf-8")
        return decision
    variants = hv.stage_b_variants(base)
    results = [exp.run_variant(v) for v in variants]
    v0 = load_variant(exp, "V0")
    units = run_units(exp.out_dir)
    order = [v.name for v in variants]
    decision = select(results, v0, static_prev1(exp), units, order)
    decision["applicable"] = True
    decision["calibration"] = base.name
    path.write_text(json.dumps(hv.jsonable(decision), indent=2), encoding="utf-8")
    print("Stage B winner:", decision["winner"], decision["label"], flush=True)
    return decision


# --- report ------------------------------------------------------------------------------------------------------

def _f(v, nd=3):
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{nd}f}"


def _ci(m, key):
    return f"{_f(m[key])} [{_f(m[key + '_ci_lo'])}, {_f(m[key + '_ci_hi'])}]"


def report(exp: Experiment) -> str:
    units = run_units(exp.out_dir)
    base = exp.baselines()
    names = sorted(p.stem[len("variant_"):] for p in exp.out_dir.glob("variant_*.json"))
    order = ["V0", "V1", "V2k2", "V2k5", "V2k10"]
    names = sorted(names, key=lambda n: (order.index(n.split("-")[0]) if n.split("-")[0] in order else 99, n))
    results = {n: load_variant(exp, n) for n in names}
    v0 = results["V0"]
    sp1 = base["rob"]["prev_1"]["static_limits"]["cost_per_part"]
    crit = {n: criteria(r, v0, sp1, units) for n, r in results.items()}
    lines = ["# Scoring experiment: result tables (generated by scripts/scoring_experiment.py; do not hand-edit)", ""]
    lines += ["## P1: clean-lot flag rate (no defective parts), share of parts at or above the TUNED REVIEW threshold", "",
              "| variant | REVIEW threshold | pooled | lots 10+ | " + " | ".join(hv.FAMILY_NAMES) + " | shipped-threshold share |",
              "|---|---|" + "---|" * (3 + len(hv.FAMILY_NAMES)) + ""]
    for n, r in results.items():
        p1 = r["p1"]
        lines.append(f"| {n} | {_f(p1['threshold_review'], 4)} | {_f(p1['share_flagged_pooled'])} | "
                     f"{_f(p1['share_flagged_lots_10_plus'])} | " + " | ".join(_f(p1['per_family'][f]) for f in hv.FAMILY_NAMES)
                     + f" | {_f(p1.get('share_flagged_at_shipped_thresholds'))} |")
    lines += ["", "## Held-out headline, REVIEW operating point (95% CI over lots), tuned thresholds", "",
              "| variant | flag rate | recall | precision | false alarms | missed | cost per part |", "|---|---|---|---|---|---|---|"]
    def row(label, m):
        return (f"| {label} | {_ci(m, 'flag_rate')} | {_ci(m, 'recall')} | {_ci(m, 'precision')} | "
                f"{m['false_alarms']} | {m['missed']} | {_ci(m, 'cost_per_part')} |")
    if "eval_shipped_thresholds" in v0:
        lines.append(row("V0 (today, shipped thresholds)", v0["eval_shipped_thresholds"]["review"]))
    for n, r in results.items():
        lines.append(row(n, r["eval"]["review"]))
    for m, v in base["eval"]["ALL"].items():
        lines.append(row(f"baseline {m}", v))
    lines += ["", "## Held-out headline, REJECT operating point (pre-cap)", "",
              "| variant | flag rate | recall | precision | false alarms | missed | cost per part |", "|---|---|---|---|---|---|---|"]
    if "eval_shipped_thresholds" in v0:
        lines.append(row("V0 (today, shipped thresholds)", v0["eval_shipped_thresholds"]["reject"]))
    for n, r in results.items():
        lines.append(row(n, r["eval"]["reject"]))
    lines += ["", "## Per-family cost per part at REVIEW (S5 compares with re-tuned V0)", "",
              "| variant | " + " | ".join(hv.FAMILY_NAMES) + " |", "|---|" + "---|" * len(hv.FAMILY_NAMES)]
    for n, r in results.items():
        lines.append(f"| {n} | " + " | ".join(_f(r["eval"]["per_family_cost_review"][f]) for f in hv.FAMILY_NAMES) + " |")
    for m in BASELINE_METHODS:
        lines.append(f"| baseline {m} | " + " | ".join(_f(base["eval_per_family_cost"][m].get(f)) for f in hv.FAMILY_NAMES) + " |")
    lines += ["", "## Robustness at REVIEW, thresholds fixed (cost per part [95% CI] / flag rate / recall)", "",
              "| variant | " + " | ".join(hv.SETTINGS) + " |", "|---|" + "---|" * len(hv.SETTINGS)]
    for n, r in results.items():
        lines.append(f"| {n} | " + " | ".join(
            f"{_ci(r['robustness'][s]['review'], 'cost_per_part')} / {_f(r['robustness'][s]['review']['flag_rate'])} / "
            f"{_f(r['robustness'][s]['review']['recall'])}" for s in hv.SETTINGS) + " |")
    for m in ("static_limits", "dynamic_pat"):
        lines.append(f"| baseline {m} | " + " | ".join(
            f"{_ci(base['rob'][s][m], 'cost_per_part')} / {_f(base['rob'][s][m]['flag_rate'])} / {_f(base['rob'][s][m]['recall'])}"
            for s in hv.SETTINGS) + " |")
    lines += ["", "## Success criteria", "",
              "| variant | S1 (P1 P2 P3 P4 P5) | S2 recall>=0.75 | S3 cost<=0.22 | S4 prev-1% cost<=static | S5 worst family +cost<=0.03 | ALL |",
              "|---|---|---|---|---|---|---|"]
    def pf(b):
        return "PASS" if b else "FAIL"
    for n, c in crit.items():
        s1 = c["S1_parts"]
        v = c["values"]
        lines.append(f"| {n} | {pf(c['S1'])} ({' '.join(k + ':' + ('-' if s1[k] is None else 'P' if s1[k] else 'F') for k in ('P1', 'P2', 'p3', 'p4', 'p5'))}) | "
                     f"{pf(c['S2'])} ({_f(v['recall'])}) | {pf(c['S3'])} ({_f(v['cost'])}) | "
                     f"{pf(c['S4'])} ({_f(v['prev1_cost'])} vs {_f(v['static_limits_prev1_cost'])}) | "
                     f"{pf(c['S5'])} ({_f(v['worst_family_extra_cost_vs_v0'])}) | {pf(c['all'])} |")
    lines += ["", "## S6 (informational): leave-one-family-out thresholds", "",
              "| variant | recall | cost | S2 | S3 | S5 |", "|---|---|---|---|---|---|"]
    for n, c in crit.items():
        s6 = c["S6_informational"]
        lines.append(f"| {n} | {_f(s6['recall'])} | {_f(s6['cost'])} | {pf(s6['S2'])} | {pf(s6['S3'])} | {pf(s6['S5'])} |")
    lines += ["", "## Golden example (P2) at the tuned thresholds", "", "| variant | cold score | cold REJECT | warm score | warm REJECT |",
              "|---|---|---|---|---|"]
    for n, r in results.items():
        p2 = r["p2"]
        lines.append(f"| {n} | {_f(p2['cold']['score'], 3)} | {p2['cold']['reject']} | {_f(p2['warm']['score'], 3)} | {p2['warm']['reject']} |")
    lines += ["", "## Thresholds tuned on the tuning side", "", "| variant | REVIEW | REJECT | tuning parts | tuning defective |",
              "|---|---|---|---|---|"]
    for n, r in results.items():
        lines.append(f"| {n} | {_f(r['thresholds']['review'], 4)} | {_f(r['thresholds']['reject'], 4)} | "
                     f"{r['tuning_parts']} | {r['tuning_defective']} |")
    text = "\n".join(lines) + "\n"
    (exp.out_dir / "SUMMARY.md").write_text(text, encoding="utf-8")
    (exp.out_dir / "criteria.json").write_text(json.dumps(hv.jsonable(crit), indent=2), encoding="utf-8")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("prepare", "stage-a", "stage-b", "units", "report", "all"))
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--cache", type=Path, default=CACHE_DIR)
    for side in hv.SIDES:
        parser.add_argument(f"--{side}-lots", type=int, default=None, help=f"override lots per family on the {side} side")
    args = parser.parse_args(argv)
    exp = Experiment(out_dir=args.out, cache_dir=args.cache,
                     lots={s: getattr(args, f"{s}_lots") for s in hv.SIDES if getattr(args, f"{s}_lots") is not None})
    if args.stage in ("prepare", "all"):
        for kind in ("tune", "eval", "clean", "rob"):
            exp.prepared(kind)
        exp.baselines()
    if args.stage in ("units", "all"):
        run_units(exp.out_dir)
    if args.stage in ("stage-a", "all"):
        stage_a(exp)
    if args.stage in ("stage-b", "all"):
        stage_b(exp)
    if args.stage in ("report", "all"):
        print(report(exp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
