"""E5 step 3 / IMPLEMENTATION_PLAN.md Part 7.2: the golden test's fixture - the problem statement's own
worked example, built once here and run by tests/integration/test_golden_module_a.py.

    a lot with median leakage 10 uA and a part reading 45 uA, against a 50 uA datasheet limit,
    must be flagged.

The lot is hand-built, not generated: every number in it is chosen so a reviewer can check it by hand.
    - 77 parts (ScreeningConfig.lot_size_default, above the 30-part pooled-fallback minimum, so MCD fits)
    - leakage in uA, the problem statement's unit (the generator's own leakage is in nA - deliberately not
      reused here); lot median exactly 10 uA at every checkpoint, the golden part exactly 45 uA at every
      checkpoint, every part below the 50 uA limit at every checkpoint
    - healthy parts spread symmetrically around the median and drift slightly apart over burn-in, so no
      delta is degenerate (a flat lot would turn this into the zero-MAD edge case instead)
    - the golden part is exactly at the lot median on Iddq and delay, so leakage alone can explain a flag
    - a part number with no history, so Isolation Forest is in cold start (E2 step 3) and the flag has to
      come from the explainable, lot-relative detectors - the ones E12's gate lets reach REJECT
"Flagged" means any severity tier above PASS (REVIEW or REJECT): the problem statement asks for the part to
be flagged, not for a particular tier, and the tier depends on harness-tuned thresholds (P1.7) that do not
exist yet.

`golden_feature_frames()` builds Module A's contracted input by hand (E2 step 1's robust z, lot-relative, per
checkpoint), so the Module A golden test does not depend on P2's features stage being real. The integration
suite separately runs the same lot through features.compute() and fusion.run_full_pipeline() once those exist.

`TEMP_detect_module_a` is a TEMP_ stub for a contract gap (CONTRACT_CHANGES.md, 2026-09-25 P1): the plan names
`module_a.detect()` (Part 5.7) but never freezes its signature. Assumed here: detect(list[FeatureFrame]) ->
list[ModuleAResult], one result per input frame. Swap for the real call once the Lead pins it.
"""
import importlib
from collections.abc import Iterable
from types import ModuleType

import numpy as np

from contracts import FeatureFrame, LotDataset, ModuleAResult, Reading, ScreeningConfig
from harness.industry_baselines import Limit, robust_center_sigma

GOLDEN_LOT_MEDIAN_UA = 10.0
GOLDEN_PART_VALUE_UA = 45.0
GOLDEN_DATASHEET_LIMIT_UA = 50.0
GOLDEN_PARAMETER = "leakage"
GOLDEN_UNIT = "uA"

GOLDEN_LOT_ID = "GOLDEN-LOT-01"
GOLDEN_PART_NUMBER = "PN-GOLDEN"
GOLDEN_COMPONENT_ID = "GOLDEN-045"
GOLDEN_ACCOUNT_ID = "harness"
GOLDEN_LOT_SIZE = ScreeningConfig().lot_size_default  # 77

CHECKPOINT_HOURS = (0.0, 24.0, 96.0, 168.0)
FEATURE_CHECKPOINTS = {"0h": 0.0, "24h": 24.0, "96h": 96.0}  # the 0h/24h/96h horizon - never 168h

# (center, half-width of the healthy spread at 0h, unit). Iddq and delay centers are the generator's own
# lot centers (generator/parameters.py); leakage is the worked example's 10 uA.
_PARAMETERS = {
    "iddq": (12.0, 2.4, "uA"),
    "leakage": (GOLDEN_LOT_MEDIAN_UA, 3.0, GOLDEN_UNIT),
    "prop_delay": (5.0, 0.4, "ns"),
}
_SPREAD_GROWTH_AT_168H = 0.10  # healthy parts drift 10% further from the median by 168h

_N_HEALTHY = GOLDEN_LOT_SIZE - 1
_N_SIDE = (_N_HEALTHY - 2) // 2  # 37 below the median, 2 exactly on it, 37 above
assert 2 * _N_SIDE + 2 == _N_HEALTHY, "lot size must leave two healthy parts exactly on the median"


class GoldenTestUnavailable(RuntimeError):
    """The stage the golden test needs does not exist on this branch yet - reported as a skip, not a pass."""


def component_ids() -> list[str]:
    return [f"G-{i:03d}" for i in range(1, _N_HEALTHY + 1)] + [GOLDEN_COMPONENT_ID]


def _healthy_offsets() -> np.ndarray:
    """Unit offsets in [-1, 1], symmetric around 0 with two parts exactly on it; deterministic, no RNG.
    Interleaved so neighbouring component IDs are not neighbouring values."""
    side = np.arange(1, _N_SIDE + 1) / _N_SIDE
    offsets = np.concatenate([-side, side, [0.0, 0.0]])
    order = np.argsort((np.arange(offsets.size) * 29) % offsets.size, kind="stable")
    return offsets[order]


def median_component_ids() -> list[str]:
    """The healthy parts sitting exactly on the lot median, on every parameter, at every checkpoint."""
    ids = component_ids()[:_N_HEALTHY]
    return [c for c, o in zip(ids, _healthy_offsets()) if o == 0.0]


def _value(parameter: str, component_index: int, hour: float) -> float:
    center, half_width, _ = _PARAMETERS[parameter]
    if component_index == _N_HEALTHY:  # the golden part
        return GOLDEN_PART_VALUE_UA if parameter == GOLDEN_PARAMETER else center
    growth = 1.0 + _SPREAD_GROWTH_AT_168H * hour / CHECKPOINT_HOURS[-1]
    return float(center + half_width * growth * _healthy_offsets()[component_index])


def golden_lot() -> LotDataset:
    """The worked example as a COMPLETE lot: 77 parts x 3 parameters x 0/24/96/168h."""
    readings = [
        Reading(component_id=component_id, lot_id=GOLDEN_LOT_ID, part_number=GOLDEN_PART_NUMBER,
                manufacturer="GOLDEN-MFR", date_code="2601", parameter=parameter, checkpoint_hour=hour,
                value=_value(parameter, index, hour), unit=unit)
        for index, component_id in enumerate(component_ids())
        for parameter, (_, _, unit) in _PARAMETERS.items()
        for hour in CHECKPOINT_HOURS
    ]
    return LotDataset(lot_id=GOLDEN_LOT_ID, part_number=GOLDEN_PART_NUMBER, status="COMPLETE",
                      readings=readings, account_id=GOLDEN_ACCOUNT_ID)


def golden_datasheet_limits() -> dict[str, Limit]:
    """The worked example's 50 uA leakage max, in the shape harness.industry_baselines scores. Fresh dict."""
    return {GOLDEN_PARAMETER: Limit(upper=GOLDEN_DATASHEET_LIMIT_UA, unit=GOLDEN_UNIT)}


def golden_feature_frames() -> list[FeatureFrame]:
    """Module A's contracted input for the golden lot, built by hand from the 0h/24h/96h reads only.
    robust_z = (value - lot median) / (lot IQR / 1.35), per checkpoint (E2 step 1)."""
    lot = golden_lot()
    table: dict[tuple[str, str], dict[float, float]] = {}
    for r in lot.readings:
        if r.checkpoint_hour in FEATURE_CHECKPOINTS.values():
            table.setdefault((r.component_id, r.parameter), {})[r.checkpoint_hour] = r.value
    stats = {}
    for parameter in _PARAMETERS:
        for hour in FEATURE_CHECKPOINTS.values():
            stats[parameter, hour] = robust_center_sigma(
                [v[hour] for (_, p), v in table.items() if p == parameter])
    frames = []
    for component_id in component_ids():
        for parameter in _PARAMETERS:
            v = table[component_id, parameter]
            z = {}
            for label, hour in FEATURE_CHECKPOINTS.items():
                center, sigma = stats[parameter, hour]
                z[label] = float((v[hour] - center) / sigma)
            frames.append(FeatureFrame(
                component_id=component_id, lot_id=lot.lot_id, part_number=lot.part_number,
                parameter=parameter, value_0h=v[0.0], value_24h=v[24.0], value_96h=v[96.0],
                delta_24h=v[24.0] - v[0.0], delta_96h=v[96.0] - v[0.0],
                lot_median_0h=float(stats[parameter, 0.0][0]), lot_median_24h=float(stats[parameter, 24.0][0]),
                robust_z=z, lot_size=GOLDEN_LOT_SIZE,
                used_pooled_fallback=GOLDEN_LOT_SIZE < ScreeningConfig().small_lot_fallback_threshold,
                elapsed_hours=dict(FEATURE_CHECKPOINTS),
            ))
    return frames


def is_flagged(result: ModuleAResult) -> bool:
    return result.severity_tier != "PASS"


def golden_result(results: Iterable[ModuleAResult]) -> ModuleAResult:
    matches = [r for r in results if (r.component_id, r.parameter) == (GOLDEN_COMPONENT_ID, GOLDEN_PARAMETER)]
    assert len(matches) == 1, (
        f"expected exactly one ModuleAResult for ({GOLDEN_COMPONENT_ID}, {GOLDEN_PARAMETER}), got {len(matches)}")
    return matches[0]


def _is_self_or_parent(missing: str | None, package: str) -> bool:
    return missing is not None and (package == missing or package.startswith(missing + "."))


def resolve(package: str, attribute: str):
    """`package.attribute`, whether the attribute is exposed on the package or lives in a same-named
    submodule. Raises GoldenTestUnavailable only if the package (or a parent of it) is absent - an
    ImportError from inside it is a real failure and propagates."""
    try:
        module = importlib.import_module(package)
    except ModuleNotFoundError as exc:
        if not _is_self_or_parent(exc.name, package):
            raise
        raise GoldenTestUnavailable(f"{package}/ does not exist on this branch yet") from exc
    target = getattr(module, attribute, None)
    if target is None:
        try:
            target = importlib.import_module(f"{package}.{attribute}")
        except ModuleNotFoundError as exc:
            if exc.name != f"{package}.{attribute}":
                raise
            raise GoldenTestUnavailable(f"{package} exposes no {attribute}() yet") from exc
    if isinstance(target, ModuleType):
        target = getattr(target, attribute, None)
    if not callable(target):
        raise GoldenTestUnavailable(f"{package} exposes no callable {attribute}() yet")
    return target


def TEMP_detect_module_a(frames: list[FeatureFrame]) -> list[ModuleAResult]:
    """Call module_a.detect(frames) and hold its output to the ModuleAResult contract. TEMP_: the signature
    is assumed, not frozen - see the module docstring."""
    detect = resolve("module_a", "detect")
    results = detect(frames)
    if not isinstance(results, list):
        raise TypeError(f"module_a.detect must return a list of ModuleAResult, got {type(results).__name__}")
    return [r if isinstance(r, ModuleAResult) else ModuleAResult.model_validate(r) for r in results]
