"""E7 step 8: optional tester-offset correction, when reference/control parts are present in
the uploaded lot.

Mirrors `generator/measurement.py`'s own approach (mean(raw_ref - true_ref) over the lot's
reference parts, per checkpoint, per parameter), since that's the one worked example of this
correction already in the codebase (AGENTS.md rule 1: reuse, don't reimplement a different
algorithm for the same job).

`contracts.py`'s `Reading` has no field marking a component as a reference/control part or
carrying its known expected value - CONTRACT_CHANGES.md logs this gap. Until resolved, the
caller supplies `reference_expected` explicitly (e.g. from the upload form); a lot with no
such input gets no correction applied, matching E7 step 8's "optional... if reference/control
parts are present" - absence is the normal case, not an error.
"""
from collections import defaultdict

from contracts import Reading


def apply_tester_offset_correction(
    readings: list[Reading],
    reference_expected: dict[str, dict[str, float]] | None,
) -> list[Reading]:
    """`reference_expected` maps `component_id -> {parameter: expected_value}` for the lot's
    known reference/control parts. For each (parameter, checkpoint_hour) group that includes at
    least one reference part, the offset is `mean(raw_reference - expected_reference)` over
    just the reference parts present at that checkpoint, then subtracted from every reading
    (reference and non-reference) in that group. Groups with no reference part present are
    returned unchanged."""
    if not reference_expected:
        return readings

    groups: dict[tuple[str, float], list[Reading]] = defaultdict(list)
    for reading in readings:
        groups[(reading.parameter, reading.checkpoint_hour)].append(reading)

    corrected: list[Reading] = []
    for (parameter, _checkpoint_hour), group in groups.items():
        deviations = [
            reading.value - reference_expected[reading.component_id][parameter]
            for reading in group
            if reading.component_id in reference_expected and parameter in reference_expected[reading.component_id]
        ]
        if not deviations:
            corrected.extend(group)
            continue
        offset = sum(deviations) / len(deviations)
        corrected.extend(reading.model_copy(update={"value": reading.value - offset}) for reading in group)
    return corrected
