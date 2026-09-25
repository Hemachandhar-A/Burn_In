"""E5 step 3 / IMPLEMENTATION_PLAN.md Part 7.2: the golden test's fixture - the problem statement's own
worked example, built once here and run by tests/integration/test_golden_module_a.py
(pinned by tests/unit/harness/test_harness_golden_fixture.py and test_p16_edge_cases.py).

    a lot with median leakage 10 uA and a part reading 45 uA, against a 50 uA datasheet limit,
    must be flagged.

The lot is hand-built, not generated: every number in it is chosen so a reviewer can check it by hand.
    - 77 parts, pinned here - not read from ScreeningConfig.lot_size_default, which Settings can edit live
      (Part 5.1): the worked example must not change shape because a default did. 77 is above the 30-part
      pooled-fallback minimum, so the lot's own robust statistics hold and MCD fits
    - leakage in uA, the problem statement's unit (the generator's own leakage is in nA - deliberately not
      reused here); lot median exactly 10 uA at every checkpoint, the golden part exactly 45 uA at every
      checkpoint, every part below the 50 uA limit at every checkpoint. The lot enters after ingestion's unit
      normalization (E7 step 6), and Module A's statistics are lot-relative, so the unit cannot move a z-score
    - healthy parts spread symmetrically around the median and drift slightly apart over burn-in, so no
      delta is degenerate (a flat lot would turn this into the zero-MAD edge case instead)
    - the golden part is exactly at the lot median on Iddq and delay, so leakage alone can explain a flag
    - a part number with no history, so Isolation Forest is in cold start (E2 step 3) and the flag has to
      come from the explainable, lot-relative detectors - the ones E12's gate lets reach REJECT
"Flagged" means severity_tier REVIEW or REJECT on a ModuleAResult, and verdict WATCH or REJECT on a
RiskAssessment: the problem statement asks for the part to be flagged, not for a particular tier, and the tier
depends on harness-tuned thresholds (P1.7) that do not exist yet. Anything outside the contracted vocabulary
(AGENTS.md rule 10) is an error, never counted either way.

`golden_feature_frames()` builds Module A's contracted input by hand (E2 step 1's robust z, lot-relative, per
checkpoint), so the Module A golden test does not depend on P2's features stage being real. The lot is COMPLETE,
so the frames carry its real 168h reads too - value_168h, delta_168h, robust_z["168h"], elapsed_hours["168h"] -
because Module A is the post-hoc full-series screen (context.md 7.1; CONTRACT_CHANGES.md, 2026-09-25 Lead
SUPERSEDES entry). At 168h the golden part still reads 45 uA while the healthy spread has widened 10%, so its
168h robust z is the lowest of its four - the flag must survive the lot's own burn-in drift, not just the
tight 0h spread. Its delta_168h is 0 against a healthy delta median of 0: it is a static level outlier, not a
drifter, which is exactly the worked example. AGENTS.md rule 6 bounds Module B's inputs (0h/24h), not this
frame: each checkpoint's statistics use only that checkpoint's reads, and no 168h value feeds a 0h/24h field. The integration
suite separately runs the same lot through features.compute() and fusion.run_full_pipeline() once those exist.

Every stage is reached through `resolve()`: a stage whose top-level package is absent from the repo raises
GoldenTestUnavailable (the integration suite skips, with the reason); a stage that exists but lacks its entry
point raises GoldenEntryPointMissing (a failure - skipping would hide the golden test for good); an import
error from inside a stage propagates. A namespace package that is not at the repo root - pytest's default
import mode puts tests/unit on sys.path, so Part 4's tests/unit/module_a/ imports as `module_a` - is not the
stage. Every stage output is re-validated against its contract, including instances built with
model_construct, which skip validation.

`TEMP_detect_module_a` and `TEMP_features_compute` are TEMP_ stubs for contract gaps (CONTRACT_CHANGES.md,
2026-09-25 P1): the plan names `module_a.detect()` and `features.compute()` (Part 5.7) but never freezes
their signatures. Assumed here: detect(list[FeatureFrame]) -> list[ModuleAResult], one result per input
frame; compute(LotDataset) -> list[FeatureFrame]. Swap for the real calls once the Lead pins them.
`run_golden_pipeline` calls fusion.pipeline.run_full_pipeline(lot, config), whose signature Part 5.7 does fix.
"""
import importlib
import inspect
import os
from collections.abc import Iterable
from pathlib import Path
from types import MappingProxyType, ModuleType

import numpy as np
from pydantic import BaseModel

from contracts import (
    AnalysisResults,
    FeatureFrame,
    LotDataset,
    ModuleAResult,
    Reading,
    RiskAssessment,
    ScreeningConfig,
)
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
GOLDEN_LOT_SIZE = 77  # context.md 3.3's typical lot; pinned, not ScreeningConfig.lot_size_default (see above)

CHECKPOINT_HOURS = (0.0, 24.0, 96.0, 168.0)
# Module A's checkpoints on a COMPLETE lot: the full recorded series, 168h included (context.md 7.1). Read-only.
FEATURE_CHECKPOINTS = MappingProxyType({"0h": 0.0, "24h": 24.0, "96h": 96.0, "168h": 168.0})

# (center, half-width of the healthy spread at 0h, unit). Iddq and delay centers are the generator's own
# lot centers (generator/parameters.py); leakage is the worked example's 10 uA. Read-only, like PARAMETERS.
_PARAMETERS = MappingProxyType({
    "iddq": (12.0, 2.4, "uA"),
    "leakage": (GOLDEN_LOT_MEDIAN_UA, 3.0, GOLDEN_UNIT),
    "prop_delay": (5.0, 0.4, "ns"),
})
_SPREAD_GROWTH_AT_168H = 0.10  # healthy parts drift 10% further from the median by 168h

_N_HEALTHY = GOLDEN_LOT_SIZE - 1
_N_SIDE = (_N_HEALTHY - 2) // 2  # 37 below the median, 2 exactly on it, 37 above
if 2 * _N_SIDE + 2 != _N_HEALTHY:  # a real check, not an assert: it must survive python -O
    raise RuntimeError("golden lot size must leave two healthy parts exactly on the median")

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FLAGGED_TIERS = {"PASS": False, "REVIEW": True, "REJECT": True}  # ModuleAResult.severity_tier
_FLAGGED_VERDICTS = {"PASS": False, "WATCH": True, "REJECT": True}  # RiskAssessment.verdict
_CONTRACT_GAP = "CONTRACT_CHANGES.md, 2026-09-25 P1"


class GoldenTestUnavailable(RuntimeError):
    """The stage the golden test needs does not exist on this branch yet - reported as a skip, not a pass."""


class GoldenEntryPointMissing(AttributeError):
    """The stage exists but does not expose the entry point the plan names - a failure, never a skip."""


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


def _value(parameter: str, component_index: int, hour: float, offsets: np.ndarray) -> float:
    center, half_width, _ = _PARAMETERS[parameter]
    if component_index == _N_HEALTHY:  # the golden part
        return GOLDEN_PART_VALUE_UA if parameter == GOLDEN_PARAMETER else center
    growth = 1.0 + _SPREAD_GROWTH_AT_168H * hour / CHECKPOINT_HOURS[-1]
    return float(center + half_width * growth * offsets[component_index])


def golden_lot() -> LotDataset:
    """The worked example as a COMPLETE lot: 77 parts x 3 parameters x 0/24/96/168h."""
    offsets = _healthy_offsets()
    readings = [
        Reading(component_id=component_id, lot_id=GOLDEN_LOT_ID, part_number=GOLDEN_PART_NUMBER,
                manufacturer="GOLDEN-MFR", date_code="2601", parameter=parameter, checkpoint_hour=hour,
                value=_value(parameter, index, hour, offsets), unit=unit)
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
    """Module A's contracted input for the golden lot, built by hand from every checkpoint of the COMPLETE lot.
    robust_z = (value - lot median) / (lot IQR / 1.35), per checkpoint (E2 step 1). The statistics are always
    this lot's own, so used_pooled_fallback is False by construction - it describes what was computed, not
    what ScreeningConfig's threshold would have chosen. Every frame gets its own dicts."""
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
                parameter=parameter, value_0h=v[0.0], value_24h=v[24.0], value_96h=v[96.0], value_168h=v[168.0],
                delta_24h=v[24.0] - v[0.0], delta_96h=v[96.0] - v[0.0], delta_168h=v[168.0] - v[0.0],
                lot_median_0h=float(stats[parameter, 0.0][0]), lot_median_24h=float(stats[parameter, 24.0][0]),
                robust_z=z, lot_size=GOLDEN_LOT_SIZE, used_pooled_fallback=False,
                elapsed_hours=dict(FEATURE_CHECKPOINTS),
            ))
    return frames


# --- flag definitions and result selection -----------------------------------------------------------------

def is_flagged(result: ModuleAResult) -> bool:
    tier = result.severity_tier
    if tier not in _FLAGGED_TIERS:
        raise ValueError(f"severity_tier {tier!r} is not in the ModuleAResult contract {sorted(_FLAGGED_TIERS)}")
    return _FLAGGED_TIERS[tier]


def assessment_flagged(assessment: RiskAssessment) -> bool:
    verdict = assessment.verdict
    if verdict not in _FLAGGED_VERDICTS:
        raise ValueError(f"verdict {verdict!r} is not in the RiskAssessment contract {sorted(_FLAGGED_VERDICTS)}")
    return _FLAGGED_VERDICTS[verdict]


def _pairs_preview(results: list[ModuleAResult], limit: int = 5) -> str:
    pairs = sorted({(r.component_id, r.parameter) for r in results})
    more = f" ... (+{len(pairs) - limit} more)" if len(pairs) > limit else ""
    return f"{pairs[:limit]}{more}"


def golden_result(results: Iterable[ModuleAResult]) -> ModuleAResult:
    """The one result for (golden part, leakage). Raises AssertionError explicitly - never a bare assert."""
    results = list(results)
    matches = [r for r in results if (r.component_id, r.parameter) == (GOLDEN_COMPONENT_ID, GOLDEN_PARAMETER)]
    if len(matches) != 1:
        raise AssertionError(
            f"expected exactly one ModuleAResult for ({GOLDEN_COMPONENT_ID}, {GOLDEN_PARAMETER}), got "
            f"{len(matches)}; returned pairs: {_pairs_preview(results)}")
    return matches[0]


def median_results(results: Iterable[ModuleAResult]) -> list[ModuleAResult]:
    """Exactly one result per (median part, parameter) - so the control cannot pass on an empty list."""
    results = list(results)
    wanted = {(c, p) for c in median_component_ids() for p in _PARAMETERS}
    got = [r for r in results if (r.component_id, r.parameter) in wanted]
    counts: dict[tuple[str, str], int] = {}
    for r in got:
        counts[r.component_id, r.parameter] = counts.get((r.component_id, r.parameter), 0) + 1
    bad = sorted(pair for pair in wanted if counts.get(pair, 0) != 1)
    if bad:
        raise AssertionError(f"expected exactly one ModuleAResult per median-part pair; missing or duplicated: "
                             f"{bad}; returned pairs: {_pairs_preview(results)}")
    return got


def golden_assessment(results) -> RiskAssessment:
    """The one RiskAssessment for the golden part in the golden lot, from a validated AnalysisResults."""
    analysis = _validate(AnalysisResults, results, "fusion.run_full_pipeline")
    matches = [a for a in analysis.assessments if a.component_id == GOLDEN_COMPONENT_ID]
    if len(matches) != 1 or matches[0].lot_id != GOLDEN_LOT_ID:
        found = [(a.component_id, a.lot_id) for a in analysis.assessments][:5]
        raise AssertionError(f"expected exactly one RiskAssessment for {GOLDEN_COMPONENT_ID} in {GOLDEN_LOT_ID}, "
                             f"got {len(matches)}; first assessments returned: {found}")
    return matches[0]


# --- reaching the stages ---------------------------------------------------------------------------------

def _same_path(a, b) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _is_stray_namespace(module: ModuleType, name: str) -> bool:
    """A namespace package (no __init__.py) with no portion at <repo root>/<name> - e.g. tests/unit/<name>/."""
    spec = getattr(module, "__spec__", None)
    if spec is None or spec.origin is not None or spec.submodule_search_locations is None:
        return False
    return not any(_same_path(location, _REPO_ROOT / name) for location in spec.submodule_search_locations)


def _import_or_missing(dotted: str, what: str) -> ModuleType:
    try:
        return importlib.import_module(dotted)
    except ModuleNotFoundError as exc:
        if exc.name is None or not (dotted == exc.name or dotted.startswith(exc.name + ".")):
            raise  # something the stage itself imports is missing: a real failure
        raise GoldenEntryPointMissing(f"{dotted} does not exist, but {what}") from exc


def resolve(package: str, attribute: str):
    """`package.attribute`, whether the attribute is exposed on the package or lives in a same-named
    submodule. GoldenTestUnavailable if the top-level package is absent; GoldenEntryPointMissing if it exists
    but the entry point does not; any other import error propagates."""
    top = package.split(".")[0]
    try:
        top_module = importlib.import_module(top)
    except ModuleNotFoundError as exc:
        if exc.name != top:
            raise
        raise GoldenTestUnavailable(f"{top}/ does not exist on this branch yet") from exc
    if _is_stray_namespace(top_module, top):
        raise GoldenTestUnavailable(
            f"{top}/ does not exist on this branch yet (only a stray namespace package: "
            f"{list(top_module.__spec__.submodule_search_locations)})")
    exists = f"{top}/ exists - expected {package}.{attribute}() (IMPLEMENTATION_PLAN.md Part 5.7)"
    module = top_module if package == top else _import_or_missing(package, exists)
    target = getattr(module, attribute, None)
    if target is None:
        target = _import_or_missing(f"{package}.{attribute}", exists)
    if isinstance(target, ModuleType):
        target = getattr(target, attribute, None)
    if not callable(target):
        raise GoldenEntryPointMissing(f"{package} exposes no callable {attribute}(), but {exists}")
    return target


def _check_signature(fn, name: str, where: str, *args) -> None:
    """Name a signature mismatch as the contract gap it is, before calling - so a TypeError raised inside the
    stage itself is never mistaken for one (or rewritten)."""
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):  # no introspectable signature: just call it
        return
    try:
        signature.bind(*args)
    except TypeError as exc:
        raise TypeError(f"{name}{signature} does not accept the call the golden test makes ({where})") from exc


def _validate(model: type[BaseModel], item, source: str):
    """Hold one stage output to its contract. A model instance is re-validated from its dump, since
    model_construct skips validation; dicts and same-shaped objects are validated too."""
    if isinstance(item, BaseModel):
        item = item.model_dump()
    if item is None or isinstance(item, (str, bytes, int, float)):
        raise TypeError(f"{source} returned {type(item).__name__}, not a {model.__name__}")
    return model.model_validate(item, from_attributes=True)


def _validate_list(model: type[BaseModel], items, source: str) -> list:
    if not isinstance(items, (list, tuple)):
        raise TypeError(f"{source} must return a list of {model.__name__}, got {type(items).__name__}")
    return [_validate(model, item, source) for item in items]


def TEMP_detect_module_a(frames: list[FeatureFrame]) -> list[ModuleAResult]:
    """module_a.detect(frames), held to the ModuleAResult contract. TEMP_: signature assumed, not frozen."""
    detect = resolve("module_a", "detect")
    _check_signature(detect, "module_a.detect", f"detect(frames) - TEMP_ assumption, see {_CONTRACT_GAP}", frames)
    return _validate_list(ModuleAResult, detect(frames), "module_a.detect")


def TEMP_features_compute(lot: LotDataset) -> list[FeatureFrame]:
    """features.compute(lot), held to the FeatureFrame contract. TEMP_: signature assumed, not frozen."""
    compute = resolve("features", "compute")
    _check_signature(compute, "features.compute", f"compute(lot) - TEMP_ assumption, see {_CONTRACT_GAP}", lot)
    return _validate_list(FeatureFrame, compute(lot), "features.compute")


def run_golden_pipeline():
    """fusion.pipeline.run_full_pipeline(golden_lot(), ScreeningConfig()) - Part 5.7's frozen signature.
    Returns the raw output; golden_assessment() validates it."""
    run = resolve("fusion.pipeline", "run_full_pipeline")
    lot, config = golden_lot(), ScreeningConfig()
    _check_signature(run, "fusion.pipeline.run_full_pipeline",
                     "run_full_pipeline(lot, config) - IMPLEMENTATION_PLAN.md Part 5.7", lot, config)
    return run(lot, config)
