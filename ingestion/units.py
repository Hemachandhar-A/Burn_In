"""E7 step 6: unit normalization to a canonical unit per parameter before any downstream
processing.

For the three modeled parameters, the canonical unit is `generator.parameters.PARAMETERS`'s
own unit (calling a read-only registry another owner exposes, per AGENTS.md rule 2 - not
editing generator/). For an unrecognized parameter (context.md 5.9), there is no registry
entry to convert against: the first unit seen for that parameter in the lot becomes its
canonical unit, and every other row for that parameter is converted to it if the units share
a recognized physical family; a genuinely incompatible unit (e.g. a time unit under a current
parameter) can't be converted and is a validation error, not a silent pass-through.
"""
from generator.parameters import PARAMETERS

# Multiplicative factor to the family's SI base unit (A for current, s for time).
_CURRENT_UNITS = {"a": 1.0, "ma": 1e-3, "ua": 1e-6, "na": 1e-9, "pa": 1e-12}
_TIME_UNITS = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12}
_UNIT_FAMILIES = (_CURRENT_UNITS, _TIME_UNITS)


def _normalize_unit_name(unit: str) -> str:
    return unit.strip().lower()


def _family_for(unit: str) -> dict[str, float] | None:
    normalized = _normalize_unit_name(unit)
    for family in _UNIT_FAMILIES:
        if normalized in family:
            return family
    return None


class UnitMismatchError(ValueError):
    """Raised when two units for the same parameter belong to different physical families
    (e.g. `uA` and `ns`) - not something a multiplicative conversion can reconcile."""


def is_recognized_parameter(parameter: str) -> bool:
    """E7 step 10: whether `parameter` is one of the three modeled parameters. An unrecognized
    parameter is still a valid `Reading` (context.md 5.9) - Module A scores it generically,
    Module B declines to forecast it - this just lets a caller tell the two cases apart."""
    return parameter in PARAMETERS


def canonical_unit_for(parameter: str, observed_unit: str) -> str:
    """The unit `parameter`'s values should be normalized to: the modeled parameters' own
    registry unit, or (for an unrecognized parameter) whatever unit was first observed."""
    spec = PARAMETERS.get(parameter)
    return spec.unit if spec is not None else observed_unit


def convert_value(value: float, from_unit: str, to_unit: str) -> float:
    """Converts `value` from `from_unit` to `to_unit`, both within the same recognized
    physical-quantity family (current or time). Units that already match are returned as-is,
    including units outside both known families (nothing to convert, nothing to mismatch)."""
    if _normalize_unit_name(from_unit) == _normalize_unit_name(to_unit):
        return value
    from_family = _family_for(from_unit)
    to_family = _family_for(to_unit)
    if from_family is None or to_family is None or from_family is not to_family:
        raise UnitMismatchError(
            f"cannot convert '{from_unit}' to '{to_unit}' - not the same recognized unit family"
        )
    from_factor = from_family[_normalize_unit_name(from_unit)]
    to_factor = to_family[_normalize_unit_name(to_unit)]
    return value * from_factor / to_factor


def normalize_readings(readings: list) -> tuple[list, list[str]]:
    """Returns `(normalized_readings, errors)`. Every reading's `value`/`unit` is converted to
    its parameter's canonical unit (E7 step 6); a genuine cross-family mismatch is reported as
    an error string per offending reading rather than raised immediately, so callers see every
    problem at once (matching `IngestionValidationError`'s "every problem, not just the first"
    convention)."""
    canonical_by_parameter: dict[str, str] = {}
    for reading in readings:
        canonical_by_parameter.setdefault(reading.parameter, canonical_unit_for(reading.parameter, reading.unit))

    normalized = []
    errors: list[str] = []
    for reading in readings:
        target_unit = canonical_by_parameter[reading.parameter]
        try:
            converted_value = convert_value(reading.value, reading.unit, target_unit)
        except UnitMismatchError as exc:
            errors.append(
                f"component '{reading.component_id}', parameter '{reading.parameter}': {exc}"
            )
            continue
        normalized.append(reading.model_copy(update={"value": converted_value, "unit": target_unit}))
    return normalized, errors
