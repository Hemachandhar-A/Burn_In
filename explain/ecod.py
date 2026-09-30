"""P5.7 explain/ecod.py: per-dimension ECOD tail-probability/outlier scores for one part.

Uses module_a.detect.fit_ecod (the same fitted ECOD detect()'s step 4 already fits internally,
exposed read-only) and PyOD 3.6.6's own per-dimension score matrix, `ECOD.O` (pyod/models/ecod.py) -
set during fit()/decision_function() as `self.O = np.maximum(self.U_skew, np.maximum(self.U_l, self.U_r))`,
one row per training sample, one column per input dimension (here: [value_0h, value_24h], module_a's
own `_value_matrix` feature scope). The identity PyOD itself uses to aggregate it into the single score
`ecod_score`/`decision_scores_` an aggregated score is summed from: `decision_scores_ = O.sum(axis=1)`
(pyod/models/ecod.py:152/154, both the sequential and n_jobs>1 path) - per-dimension contributions here
must reproduce that same sum, verified by test.
"""
from contracts import FeatureFrame
from explain.cache import ExplainCache
from explain.models import DimensionContribution, EcodExplanation
from module_a.detect import fit_ecod

_DIMENSIONS = ("value_0h", "value_24h")


def explain_ecod(
    frames: list[FeatureFrame], parameter: str, component_id: str, cache: ExplainCache | None = None,
) -> EcodExplanation:
    """Per-dimension ECOD score breakdown for one part. Raises ValueError if no frame in `frames` has
    `parameter`, or if `component_id` isn't among the frames scored for it.

    `cache` (Block 4c Part 2): when given, fit_ecod(frames, parameter) is reused for every call
    sharing the same parameter instead of refit - numerically identical (ECOD's fit has no
    randomness), only the redundant computation is removed. Default None reproduces the exact
    pre-optimization behavior (a fresh fit on every call)."""
    if cache is not None:
        if parameter not in cache.ecod_fits:
            cache.ecod_fits[parameter] = fit_ecod(frames, parameter)
        fitted = cache.ecod_fits[parameter]
    else:
        fitted = fit_ecod(frames, parameter)
    if fitted is None:
        raise ValueError(f"no frames for parameter {parameter!r}")
    component_ids, ecod = fitted
    if component_id not in component_ids:
        raise ValueError(f"{component_id!r} was not scored for parameter {parameter!r}")

    idx = component_ids.index(component_id)
    per_dimension = ecod.O[idx, :]
    aggregated = float(ecod.decision_scores_[idx])

    contributions = [
        DimensionContribution(dimension=dim, score=float(per_dimension[i]))
        for i, dim in enumerate(_DIMENSIONS)
    ]
    return EcodExplanation(
        component_id=component_id,
        parameter=parameter,
        aggregated_score=aggregated,
        contributions=contributions,
    )
