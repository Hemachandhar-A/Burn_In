"""Block 4c Part 2: a per-run cache for explain/'s three expensive fit/construct operations - not
module-level state, so two lots (or two concurrent requests) never share it. Profiling
(CONTRACT_CHANGES.md 2026-09-30) found fusion/pipeline.py's per-flagged-part explanation loop was
re-doing three deterministic, lot-scoped computations once per part instead of once per lot:

- module_a.detect.fit_mcd(frames, checkpoint) - the same fitted MinCovDet for every part sharing a
  checkpoint (explain_mcd always uses "24h" in this codebase's one caller, fusion/pipeline.py, but the
  cache is keyed by whatever checkpoint is actually passed, not hardcoded to one value).
- module_a.detect.fit_ecod(frames, parameter) - the same fitted ECOD for every part sharing a
  worst_parameter.
- shap.TreeExplainer(booster) - the same explainer for every part whose Module B model resolves to
  the same underlying booster object (same part_number/parameter/horizon, since
  module_b.predictor.synthetic_models is itself functools.cache'd per part_number).

Both fit_mcd/fit_ecod are deterministic (fit_mcd uses a fixed random_state; ECOD has none) and
TreeExplainer's construction depends only on the booster, so caching changes nothing about the
numbers produced - only how many times they are computed. Pass an ExplainCache instance to
explain_mcd/explain_ecod/explain_module_b's `cache` argument to enable it; the default `cache=None`
reproduces the exact pre-optimization behavior (a fresh fit/construct on every call)."""
from dataclasses import dataclass, field


@dataclass
class ExplainCache:
    mcd_fits: dict = field(default_factory=dict)         # checkpoint -> fit_mcd(frames, checkpoint) result
    ecod_fits: dict = field(default_factory=dict)         # parameter -> fit_ecod(frames, parameter) result
    tree_explainers: dict = field(default_factory=dict)   # id(booster) -> shap.TreeExplainer(booster)
