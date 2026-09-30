"""P5.7 explain/mcd.py: per-parameter contribution to squared Mahalanobis distance.

Uses the identity d^2 = sum_i (x_i - mu_i) * [Sigma^-1 (x - mu)]_i with the fitted MinCovDet's own
location_ and precision_ (module_a.detect.fit_mcd - the same fitted model _detect_single_lot's step 2
produces internally, exposed read-only). sklearn's MinCovDet.mahalanobis(X) itself returns the SQUARED
Mahalanobis distance (verified against sklearn's EmpiricalCovariance.mahalanobis docstring: "Returns:
Squared Mahalanobis distances") using precision = get_precision() = self.precision_ when
store_precision=True (MinCovDet's default) - so precision_ is exactly Sigma^-1, matching this formula
term for term. Per-parameter contributions may be negative (this is a decomposition of a quadratic
form, not a percentage split); they sum to the same d^2 mcd.mahalanobis([x]) returns for that row.
"""
import numpy as np

from contracts import FeatureFrame
from explain.models import MCDExplanation, ParameterContribution
from module_a.detect import fit_mcd


def explain_mcd(frames: list[FeatureFrame], checkpoint: str, component_id: str) -> MCDExplanation:
    """Per-parameter squared-Mahalanobis-distance decomposition for one part at one checkpoint.
    Raises ValueError if MCD did not run for this lot/checkpoint (below the lot-size floor, too few
    qualifying components, or a singular covariance - module_a.detect.fit_mcd's own None cases) or if
    `component_id` did not qualify for the fitted matrix (missing a parameter at this checkpoint)."""
    fitted = fit_mcd(frames, checkpoint)
    if fitted is None:
        raise ValueError(f"MCD did not run for checkpoint {checkpoint!r} on this lot")
    component_ids, parameters, mcd = fitted
    if component_id not in component_ids:
        raise ValueError(f"{component_id!r} did not qualify for the fitted MCD matrix at {checkpoint!r}")

    from features.compute import build_mcd_matrix

    _, _, matrix = build_mcd_matrix(frames, checkpoint)
    idx = component_ids.index(component_id)
    x = np.array(matrix[idx], dtype=float)
    centered = x - mcd.location_
    per_term = centered * (mcd.precision_ @ centered)
    d2 = float(np.sum(per_term))

    contributions = sorted(
        (
            ParameterContribution(parameter=p, contribution=float(per_term[i]))
            for i, p in enumerate(parameters)
        ),
        key=lambda c: abs(c.contribution),
        reverse=True,
    )
    return MCDExplanation(
        component_id=component_id,
        checkpoint=checkpoint,
        mahalanobis_distance_squared=d2,
        contributions=contributions,
    )
