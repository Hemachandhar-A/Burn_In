"""E1 step 10: quantitative realism validation (context.md 3.4 (4)).

Statistics are extracted from both the generator's output and real published measurements, and each pair is
compared with a two-sample Kolmogorov-Smirnov test (scipy.stats.ks_2samp), reporting the actual statistic and
p-value. This checks the plausibility of shape/rate statistics; it is not "validated on real data"
(context.md 3.2, 8.1).

What the real references actually contain - no per-unit raw data is published for the Latif study, so the
reference samples are what can honestly be extracted:

  Latif, Zain Ali, Hussin & Zwolinski, "Implications of Burn-In Stress on NBTI Degradation",
  arXiv:1510.01370v1 (context.md 1.4 / 3.3), PDF sha256
  b0e38f0bcf94c8eb7819772c5fe4d99f2fa64fdadefdd4f7b0aec97638d5439e.
      Table 5: measured pre -> post 168h burn-in percent change of five DAC parameters, and the fitted
      time exponent n = 0.181 (Eq. 6). Its Fig. 5 is a plotted model curve (Eq. 8), not data, so it is
      not digitized. The paper reports no measurement-repeatability numbers.

  Gao, Manut, Ji et al. (LJMU), "Reliable time exponents for long term prediction of negative bias
  temperature instability by extrapolation" - the LJMU study context.md 1.4 cites for n in 0.15-0.30,
  https://researchonline.ljmu.ac.uk/id/eprint/6810/1/FINAL%20VERSION.pdf, PDF sha256
  1021df77d99b43578b2e657b0e77b73126d51b449ac6c378ec96d8acd1dd60f3.
      Fig. 1a: 20 NBTI time exponents reported by earlier works ("data from references"), and an inset of
      484 measured degradation points with the paper's own power-law fit (n = 0.2035 printed).

Digitization: the PDF figures are vector graphics, so marker centers were read from the PDF's drawing
paths (page 1, PDF points, origin top-left) rather than eyeballed from a raster, and are stored raw here
together with the axis ticks used to calibrate them - the conversion to data units happens in code below,
so it is auditable and re-checkable. Two self-checks run in the test suite: the tick calibration maps each
labeled tick back onto its label, and refitting the digitized inset points recovers the paper's printed
n = 0.2035.

The comparison policy (gate / marginal / documented divergence) is fixed per comparison in COMPARISON_POLICY,
judged over a seed sweep, and every comparison is reported - including ones that diverge or are not computable.
"""
import argparse
import csv
import functools
import math
import numbers
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields
from pathlib import Path

import numpy as np
from scipy.stats import ks_2samp

from generator.families import GeneratorFamily, resolve_family
from generator.lot import GeneratedLot, generate_lot
from generator.parameters import PARAMETERS

ALPHA = 0.05
DEFAULT_N_LOTS = 40
_FULL_CAMPAIGN_HOURS = 168.0

# --- reference data ------------------------------------------------------------------------------

LATIF_SOURCE = "Latif et al., arXiv:1510.01370v1"
LJMU_SOURCE = "Gao et al. (LJMU eprint 6810)"

# Latif Table 5, "Percent Change" column, pre -> post 168h burn-in at 4.6 V / 115 C.
_LATIF_TABLE5_PERCENT_CHANGE = {
    "DNL mean": 6.48,
    "INL mean": 4.68,
    "Gain error": 43.50,  # the paper itself calls this spike excessive - kept, not dropped as an outlier
    "Offset error": 4.90,
    "Output current": 2.0,
}
LATIF_TIME_EXPONENT = 0.181  # Latif Eq. 6, "n = 0.181 was chosen by experiment"

# LJMU Fig. 1a main panel: y-axis major ticks (label -> PDF y in points), and the y center of each
# "data from references" marker, grouped by the citation number in the figure's legend.
_FIG1A_Y_TICKS_PT = {0.30: 286.90, 0.25: 309.13, 0.20: 331.38, 0.15: 353.62}
_FIG1A_MARKER_Y_PT = {
    "[21]": (295.75, 317.99),
    "[22]": (304.61, 322.42),
    "[23]": (326.01,),
    "[8]": (287.83,),
    "[17]": (286.84, 300.18, 322.42, 335.80),
    "[24]": (349.19,),
    "[25]": (309.11, 318.02, 322.44, 335.83, 340.26),
    "[26]": (337.60, 343.38, 362.50),
    "[27]": (326.95,),
}

# LJMU Fig. 1a inset: log-log axes. x major ticks (seconds -> PDF x), y ticks (mV -> PDF y).
_INSET_X_TICKS_PT = {10.0: 450.68, 100.0: 476.97, 1000.0: 503.32}
_INSET_Y_TICKS_PT = {10.0: 313.15, 40.0: 280.18}
_INSET_POINTS_CSV = Path(__file__).parent / "reference_data" / "ljmu_fig1a_inset_points.csv"


def _fig1a_exponent(y_pt: float) -> float:
    labels, ys = zip(*_FIG1A_Y_TICKS_PT.items())
    slope, intercept = np.polyfit(ys, labels, 1)
    return float(slope * y_pt + intercept)


def latif_168h_relative_changes() -> np.ndarray:
    """Latif Table 5's five measured 168h relative changes, as fractions."""
    return np.array([v / 100 for v in _LATIF_TABLE5_PERCENT_CHANGE.values()])


def literature_drift_exponents() -> np.ndarray:
    """21 real NBTI time exponents: LJMU Fig. 1a's 20 literature values plus Latif's n = 0.181."""
    digitized = [_fig1a_exponent(y) for ys in _FIG1A_MARKER_Y_PT.values() for y in ys]
    return np.array([round(n, 4) for n in digitized] + [LATIF_TIME_EXPONENT])


_INSET_HEADER = ["pdf_x_pt", "pdf_y_pt"]
_INSET_FRAME_PT = (443.81, 522.82, 268.61, 313.15)  # inset plot frame: x left, x right, y top, y bottom
_MIN_FIT_POINTS = 3


def _read_only(values) -> np.ndarray:
    """A float copy that can't be written through - so a frozen result object really is immutable."""
    array = np.array(values, dtype=float)
    array.setflags(write=False)
    return array


def _values_equal(a, b) -> bool:
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        return isinstance(a, np.ndarray) and isinstance(b, np.ndarray) and np.array_equal(a, b)
    return a == b


@functools.lru_cache(maxsize=8)
def _load_inset_points(path: Path) -> np.ndarray:
    """Parse the digitized inset CSV strictly: a missing header, malformed or non-finite row, or a point outside
    the inset's plot frame is refused, never skipped - a silently dropped point would change the reference."""
    with Path(path).open(encoding="utf-8-sig", newline="") as f:  # -sig: tolerate a BOM from a spreadsheet save
        lines = [line for line in f if line.strip() and not line.lstrip().startswith("#")]
    rows = list(csv.reader(lines))
    if not rows or [cell.strip() for cell in rows[0]] != _INSET_HEADER:
        raise ValueError(f"{path}: expected the header {','.join(_INSET_HEADER)}, got {rows[0] if rows else 'no rows'}")
    x_left, x_right, y_top, y_bottom = _INSET_FRAME_PT
    points = []
    for number, row in enumerate(rows[1:], start=1):
        if len(row) != 2:
            raise ValueError(f"{path}: data row {number} must have 2 fields, got {row}")
        try:
            x, y = float(row[0]), float(row[1])
        except ValueError:
            raise ValueError(f"{path}: data row {number} is not numeric: {row}") from None
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError(f"{path}: data row {number} is not finite: {row}")
        if not (x_left <= x <= x_right and y_top <= y <= y_bottom):
            raise ValueError(f"{path}: data row {number} ({x}, {y}) lies outside the inset's plot frame")
        points.append((x, y))
    if len(points) < _MIN_FIT_POINTS:
        raise ValueError(f"{path}: need at least {_MIN_FIT_POINTS} points to fit a power law, got {len(points)}")
    return _read_only(points)


@dataclass(frozen=True, eq=False)
class PowerLawFit:
    exponent: float
    n_points: int
    relative_residuals: np.ndarray  # measured / fitted - 1, per point (read-only)

    def __eq__(self, other):
        if not isinstance(other, PowerLawFit):
            return NotImplemented
        return all(_values_equal(getattr(self, f.name), getattr(other, f.name)) for f in fields(self))

    __hash__ = None  # holds an array: equality is by value, so it can't be hashed


def _log_axis_fit(ticks: dict[float, float]) -> tuple[float, float]:
    values, positions = zip(*ticks.items())
    slope, intercept = np.polyfit(positions, np.log10(values), 1)
    return float(slope), float(intercept)


def ljmu_inset_power_law_fit(path: Path = _INSET_POINTS_CSV) -> PowerLawFit:
    """Refit the LJMU inset's measured degradation points with a power law, as the paper does, and return
    each point's relative residual around that fit - the reference's noise-to-signal sample."""
    px = _load_inset_points(Path(path))
    (xs, xi), (ys, yi) = _log_axis_fit(_INSET_X_TICKS_PT), _log_axis_fit(_INSET_Y_TICKS_PT)
    log_t, log_gd = xs * px[:, 0] + xi, ys * px[:, 1] + yi
    exponent, log_a = np.polyfit(log_t, log_gd, 1)
    residuals = 10 ** (log_gd - (log_a + exponent * log_t)) - 1
    return PowerLawFit(exponent=float(exponent), n_points=len(px), relative_residuals=_read_only(residuals))


# --- generator-side extraction ---------------------------------------------------------------------

@dataclass(frozen=True, eq=False)
class GeneratorStatistics:
    """Healthy-part statistics from generated lots, pooled across the three parameters, over the 0h-168h
    campaign (reads after 168h, if any, are ignored). Every healthy series is either in an array or counted in
    the matching *_excluded field - nothing is dropped silently. Arrays are read-only."""

    family: str
    n_lots: int
    campaign_hours: tuple[float, ...]  # actual elapsed hours of the reads from 0h through the 168h read
    relative_drift_168h: np.ndarray  # measured value at 168h / measured value at 0h - 1, per part
    drift_exponent_prior: np.ndarray  # the hidden healthy power-law n actually drawn, per part
    drift_exponent_lot_fit: np.ndarray  # n fitted to the lot-median measured drift, per lot
    time_to_knee_lot: np.ndarray  # lot-median drift at the first post-0h read / at 168h, per lot
    noise_to_signal: np.ndarray  # (measured drift - true drift) / true drift, per part and post-0h read
    drift_exponent_per_part_fit: np.ndarray  # n fitted to one part's own measured drift
    relative_drift_excluded: int  # 0h reading non-positive or non-finite - a relative change is meaningless
    noise_to_signal_excluded: int  # true drift not positive - there is no signal to scale the noise by
    lot_fits_excluded: int  # lot series with a non-positive median drift (can't be log-fitted); drops the knee too
    part_fits_excluded: int  # part series with any non-positive measured drift
    lots_without_healthy_parts: int  # contribute nothing; counted so an empty lot is visible, not silent

    def __eq__(self, other):
        if not isinstance(other, GeneratorStatistics):
            return NotImplemented
        return all(_values_equal(getattr(self, f.name), getattr(other, f.name)) for f in fields(self))

    __hash__ = None  # holds arrays: equality is by value, so it can't be hashed


def _fit_exponent(hours: np.ndarray, drift: np.ndarray) -> float | None:
    if not np.all(np.isfinite(drift)) or not np.all(drift > 0):
        return None
    exponent = float(np.polyfit(np.log(hours), np.log(drift), 1)[0])
    return exponent if math.isfinite(exponent) else None


def _campaign_index(lot: GeneratedLot) -> int:
    """Index of the exact 168h read in the lot's schedule, after checking the schedule can support every
    statistic: a 0h read (the drift reference), a 168h read, and at least one read strictly between them."""
    nominal = lot.ground_truth.nominal_checkpoint_hours
    label = f"lot {lot.dataset.lot_id!r} (nominal checkpoints {nominal})"
    if not nominal or nominal[0] != 0.0:
        raise ValueError(f"{label} needs a 0h (pre-burn-in) read - every drift is measured from it")
    if _FULL_CAMPAIGN_HOURS not in nominal:
        raise ValueError(f"{label} needs a read at exactly 168h, the full campaign the references describe")
    index = nominal.index(_FULL_CAMPAIGN_HOURS)
    if index < 2:
        raise ValueError(f"{label} needs at least one read between 0h and 168h to fit a drift shape")
    return index


def _validated_lots(lots) -> list[GeneratedLot]:
    if isinstance(lots, (str, bytes, GeneratedLot)) or not isinstance(lots, Iterable):
        raise TypeError(f"lots must be a sequence of GeneratedLot, got {type(lots).__name__}")
    lots = list(lots)
    if not lots:
        raise ValueError("need at least one generated lot")
    for lot in lots:
        if not isinstance(lot, GeneratedLot):
            raise TypeError(f"expected GeneratedLot, got {type(lot).__name__}")
    seen = set()
    for lot in lots:
        key = (lot.dataset.lot_id, lot.dataset.part_number)
        # Same identity + same seed = the same random draws (generate_lot is a pure function of them, and the
        # family is deliberately not mixed in), so it would be counted as two independent samples
        # (pseudo-replication). The same identity under a different seed is a genuinely independent draw.
        draw = (*key, lot.ground_truth.seed)
        if draw in seen:
            raise ValueError(f"duplicate lot {key} with seed {lot.ground_truth.seed} - each lot may be passed only once")
        seen.add(draw)
        truth = lot.ground_truth
        if (truth.baselines.lot_id, truth.baselines.part_number) != key or (
            {p.component_id for p in truth.trajectories.parts} != {r.component_id for r in lot.dataset.readings}
        ):
            raise ValueError(f"lot {key}: its dataset and ground-truth sidecar do not describe the same parts")
    first = lots[0].ground_truth.family_spec
    if any(lot.ground_truth.family_spec != first for lot in lots):
        names = sorted({lot.ground_truth.family for lot in lots})
        raise ValueError(f"all lots must come from one generator family, got families {names}")
    return lots


def _readings_by_key(lot: GeneratedLot) -> dict[tuple[str, str, float], float]:
    readings = {}
    for r in lot.dataset.readings:
        key = (r.component_id, r.parameter, r.checkpoint_hour)
        if key in readings:
            raise ValueError(f"lot {lot.dataset.lot_id!r}: duplicate reading for {key}")
        readings[key] = r.value
    return readings


def extract_generator_statistics(lots: Iterable[GeneratedLot]) -> GeneratorStatistics:
    """Measured values come from each lot's production-facing dataset; the sidecar is used only to select
    healthy parts, read the hidden drift exponent, and get the noise-free drift the noise is measured against.

    All lots must come from one family and share one actual checkpoint schedule up to 168h (the knee reference
    is built from it) - so jittered lots can only be passed one at a time."""
    lots = _validated_lots(lots)
    index_168 = _campaign_index(lots[0])
    hours = tuple(lots[0].ground_truth.trajectories.checkpoint_hours[: index_168 + 1])
    for lot in lots[1:]:
        k = _campaign_index(lot)
        if tuple(lot.ground_truth.trajectories.checkpoint_hours[: k + 1]) != hours:
            raise ValueError(
                "all lots must share one actual checkpoint schedule up to 168h - the knee reference depends on it; "
                "generate them on one schedule with checkpoint_jitter_hours=0"
            )
    post = np.array(hours[1:])

    rel_168, n_prior, n_lot, knee, nsr, n_part = [], [], [], [], [], []
    rel_excluded = nsr_excluded = lot_excluded = part_excluded = empty_lots = 0
    for lot in lots:
        readings = _readings_by_key(lot)
        healthy = [p for p in lot.ground_truth.trajectories.parts if not p.is_defective]
        if not healthy:
            empty_lots += 1
            continue
        for name in PARAMETERS:
            lot_drifts = []
            for part in healthy:
                try:
                    m = np.array([readings[(part.component_id, name, h)] for h in hours])
                except KeyError as missing:
                    raise ValueError(f"lot {lot.dataset.lot_id!r}: missing reading {missing.args[0]}") from None
                true = np.array(part.values[name][: len(hours)])
                drift, true_drift = m[1:] - m[0], true[1:] - true[0]
                if math.isfinite(m[0]) and m[0] > 0 and math.isfinite(m[-1]):
                    rel_168.append(m[-1] / m[0] - 1)
                else:
                    rel_excluded += 1
                n_prior.append(part.drift_exponent[name])
                for d, td in zip(drift, true_drift):
                    if math.isfinite(d) and math.isfinite(td) and td > 0:
                        nsr.append((d - td) / td)
                    else:
                        nsr_excluded += 1
                fitted = _fit_exponent(post, drift)
                if fitted is None:
                    part_excluded += 1
                else:
                    n_part.append(fitted)
                lot_drifts.append(drift)
            median_drift = np.median(np.array(lot_drifts), axis=0)
            fitted = _fit_exponent(post, median_drift)
            if fitted is None:
                lot_excluded += 1
            else:
                n_lot.append(fitted)
                knee.append(median_drift[0] / median_drift[-1])
    return GeneratorStatistics(
        family=lots[0].ground_truth.family,
        n_lots=len(lots),
        campaign_hours=hours,
        relative_drift_168h=_read_only(rel_168),
        drift_exponent_prior=_read_only(n_prior),
        drift_exponent_lot_fit=_read_only(n_lot),
        time_to_knee_lot=_read_only(knee),
        noise_to_signal=_read_only(nsr),
        drift_exponent_per_part_fit=_read_only(n_part),
        relative_drift_excluded=rel_excluded,
        noise_to_signal_excluded=nsr_excluded,
        lot_fits_excluded=lot_excluded,
        part_fits_excluded=part_excluded,
        lots_without_healthy_parts=empty_lots,
    )


# --- comparisons -----------------------------------------------------------------------------------

# "gate":      the KS test must not reject at ALPHA - on any seed of the sweep, not just the default one.
# "marginal":  not rejected on a typical seed (median p over the sweep >= ALPHA) but rejected on some seeds;
#              reported with its rejection rate rather than passed or failed on one seed, which would be a
#              seed-picked result either way.
# "divergent": a known mismatch with the reference, disclosed here with its reason; the test suite checks it
#              still diverges so the disclosure can't go stale.
# Classified after a first run of every comparison over a 30-seed sweep (40 lots each), not before - the
# reasons below are what that run showed, and all six comparisons are always reported.
_MEASURED_LOT_FIT_REASON = (
    "Median p is above alpha, but some seeds reject (3/30 and 5/30 in the classification sweep). The cause is "
    "measurement noise, not the drift model: fitted to the noise-free truth, lot-level exponents sit tightly "
    "around 0.23 (sd ~0.016, narrower than the literature's ~0.044 between-study spread); fitted to the measured "
    "readings their sd is ~0.2, because the residual tester-offset correction error of each checkpoint session "
    "(~15% of a lot's 24h healthy drift) is shared by every part, so the lot median does not average it away. "
    "Same root cause as noise_to_signal_per_part."
)
COMPARISON_POLICY: dict[str, tuple[str, str]] = {
    "degradation_magnitude_168h": ("gate", ""),
    "drift_exponent_prior": ("gate", ""),
    "drift_exponent_lot_fit": ("marginal", _MEASURED_LOT_FIT_REASON),
    "time_to_knee_lot": ("marginal", _MEASURED_LOT_FIT_REASON),
    "noise_to_signal_per_part": (
        "divergent",
        ("Generator per-part measured drift scatters far more around its true drift than LJMU's lab-measured "
        "degradation scatters around its power-law fit (~4%). The measurands differ - LJMU measures the "
        "degradation itself (delta-Vth) on a lab instrument; the generator adds ~2% proportional tester noise to "
        "an absolute Iddq/leakage value (0.5% for delay) whose healthy drift is only a few percent - so this is "
        "not like-for-like, but it is the only real noise reference available and it does not support the "
        "generator's noise level. Not tuned to match: fitting one lab's delta-Vth scatter would overfit a "
        "non-comparable reference. The noise level stays a disclosed default (context.md Part 8)."),
    ),
    "drift_exponent_per_part_fit": (
        "divergent",
        ("Exponents fitted to one healthy part's three noisy post-0h readings are dominated by measurement noise "
        "(same root cause as noise_to_signal_per_part); the literature exponents come from densely sampled "
        "degradation curves. The lot-level fit (drift_exponent_lot_fit) is the closer comparison."),
    ),
}

_DESCRIPTIONS = {
    "degradation_magnitude_168h": (
        "healthy-part relative change 0h -> 168h (measured), pooled over parameters",
        f"{LATIF_SOURCE}, Table 5 (5 measured pre/post 168h percent changes)",
        ("Latif's parameters are DAC performance metrics under 1.4x-overvoltage burn-in, not Iddq/leakage/delay, "
        "each a mean over sampled units; with only 5 reference values the KS test can detect only a large mismatch."),
    ),
    "drift_exponent_prior": (
        "hidden healthy power-law exponent n drawn by the generator",
        f"{LJMU_SOURCE}, Fig. 1a (20 literature exponents, digitized) + {LATIF_SOURCE}, Eq. 6 (n = 0.181)",
        ("Literature exponents span different technologies and stress conditions, and LJMU argues part of their "
        "spread is a measurement-delay artifact; 21 reference values limit the test's power."),
    ),
    "drift_exponent_lot_fit": (
        "power-law exponent fitted to each lot's median healthy measured drift (post-0h reads)",
        f"{LJMU_SOURCE}, Fig. 1a + {LATIF_SOURCE}, Eq. 6 (21 exponents)",
        ("Fitted on three post-0h checkpoints, versus densely sampled curves in the literature; per-checkpoint "
        "tester-offset correction error is shared across the lot."),
    ),
    "time_to_knee_lot": (
        "fraction of the lot-median 168h healthy drift already reached at the first post-0h read",
        "(t1 / 168)^n for the 21 literature exponents - derived, not separately measured",
        ("The reference is derived from the same literature exponents under the power law the sources themselves "
        "use, so this is not independent evidence from the exponent comparisons - it restates them in the units "
        "Module B's 0h/24h horizon cares about."),
    ),
    "noise_to_signal_per_part": (
        "(measured drift - true drift) / true drift, per healthy part and post-0h read",
        f"{LJMU_SOURCE}, Fig. 1a inset (484 digitized measured points, relative residual around the power-law fit)",
        ("LJMU's residuals include model misfit as well as instrument noise; the generator's are measured against "
        "the exact noise-free drift."),
    ),
    "drift_exponent_per_part_fit": (
        "power-law exponent fitted to each healthy part's own measured drift (post-0h reads)",
        f"{LJMU_SOURCE}, Fig. 1a + {LATIF_SOURCE}, Eq. 6 (21 exponents)",
        "Parts whose measured drift is non-positive at any post-0h read can't be log-fitted and are excluded.",
    ),
}


_KS_DECIMALS = 12
_NAN_KEY = "nan"  # stands in for NaN in equality/hash keys: NaN != NaN, and hash(nan) is per-object


def _nan_safe(value):
    return _NAN_KEY if isinstance(value, float) and math.isnan(value) else value


class _NanSafeEquality:
    """Value equality and hashing that treat NaN fields as equal - results that are not computable carry NaN."""

    def _key(self):
        return (type(self), *(_nan_safe(getattr(self, f.name)) for f in fields(self)))

    def __eq__(self, other):
        if type(other) is not type(self):
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())


@dataclass(frozen=True, eq=False)
class RealismComparison(_NanSafeEquality):
    """One KS comparison. When the generator side has no usable values (every series excluded, or no healthy
    parts), the comparison is still reported, as not computable: generator_n = 0 and NaN statistic/p-value."""

    name: str
    family: str
    policy: str  # "gate", "marginal" or "divergent" - see COMPARISON_POLICY
    generator_statistic: str
    reference_source: str
    caveat: str
    generator_n: int
    reference_n: int
    generator_median: float
    reference_median: float
    ks_statistic: float
    p_value: float
    generator_excluded: int = 0  # generator series that couldn't be used (see GeneratorStatistics' counters)

    @property
    def computable(self) -> bool:
        return self.generator_n > 0 and math.isfinite(self.p_value)


def _compare(name: str, family: str, generator, reference, excluded: int = 0) -> RealismComparison:
    generator = np.asarray(generator, dtype=float)
    reference = np.asarray(reference, dtype=float)
    # ks_2samp does not refuse NaN - it returns a meaningless result - so a non-finite value is a bug upstream.
    if not np.all(np.isfinite(generator)):
        raise ValueError(f"{name}: generator sample contains non-finite values")
    if len(reference) == 0 or not np.all(np.isfinite(reference)):
        raise ValueError(f"{name}: reference sample must be non-empty and finite")
    # Round both samples far below any measurement resolution before comparing, so a tie is a tie: 5.10/5.00 - 1
    # is 0.020000000000000018 in binary and would otherwise sort above Latif's 2%, and least-squares exponents
    # can differ in the last bits between BLAS builds. Only representation noise is removed.
    generator = np.round(generator, _KS_DECIMALS)
    reference = np.round(reference, _KS_DECIMALS)
    statistic, source, caveat = _DESCRIPTIONS[name]
    if len(generator) == 0:
        ks, p, median = math.nan, math.nan, math.nan
    else:
        result = ks_2samp(generator, reference)
        ks, p, median = float(result.statistic), float(result.pvalue), float(np.median(generator))
    return RealismComparison(
        name=name,
        family=family,
        policy=COMPARISON_POLICY[name][0],
        generator_statistic=statistic,
        reference_source=source,
        caveat=caveat,
        generator_n=len(generator),
        reference_n=len(reference),
        generator_median=median,
        reference_median=float(np.median(reference)),
        ks_statistic=ks,
        p_value=p,
        generator_excluded=int(excluded),
    )


def compare_to_references(stats: GeneratorStatistics) -> tuple[RealismComparison, ...]:
    if not isinstance(stats, GeneratorStatistics):
        raise TypeError(f"expected GeneratorStatistics (from extract_generator_statistics), got {type(stats).__name__}")
    exponents = literature_drift_exponents()
    t1, t_168 = stats.campaign_hours[1], stats.campaign_hours[-1]
    family = stats.family
    return (
        _compare("degradation_magnitude_168h", family, stats.relative_drift_168h, latif_168h_relative_changes(),
                 stats.relative_drift_excluded),
        _compare("drift_exponent_prior", family, stats.drift_exponent_prior, exponents),
        _compare("drift_exponent_lot_fit", family, stats.drift_exponent_lot_fit, exponents,
                 stats.lot_fits_excluded),
        _compare("time_to_knee_lot", family, stats.time_to_knee_lot, (t1 / t_168) ** exponents,
                 stats.lot_fits_excluded),
        _compare("noise_to_signal_per_part", family, stats.noise_to_signal,
                 ljmu_inset_power_law_fit().relative_residuals, stats.noise_to_signal_excluded),
        _compare("drift_exponent_per_part_fit", family, stats.drift_exponent_per_part_fit, exponents,
                 stats.part_fits_excluded),
    )


def _validate_seed(seed) -> int:
    # Same rule as generate_lot, checked up front so a bad seed fails before any lot is generated.
    if isinstance(seed, bool) or not isinstance(seed, numbers.Integral):
        raise TypeError(f"seed must be an int, got {type(seed).__name__}")
    if seed < 0:
        raise ValueError(f"seed must be >= 0, got {seed}")
    return int(seed)


def run_realism_comparisons(family: "str | GeneratorFamily" = "baseline", n_lots: int = DEFAULT_N_LOTS,
                            seed: int = 0) -> tuple[RealismComparison, ...]:
    """Generate `n_lots` independent lots (one seed; lot identity is mixed into each lot's draws) on the
    default 0/24/96/168h schedule and compare them against every reference. Deterministic in its inputs."""
    if isinstance(n_lots, bool) or not isinstance(n_lots, numbers.Integral):
        raise TypeError(f"n_lots must be an int, got {type(n_lots).__name__}")
    if n_lots < 1:
        raise ValueError(f"n_lots must be >= 1, got {n_lots}")
    seed = _validate_seed(seed)
    family = resolve_family(family)
    lots = [generate_lot(f"REALISM-{k:03d}", "PN-REALISM", seed, account_id="realism-validation", family=family)
            for k in range(int(n_lots))]
    return compare_to_references(extract_generator_statistics(lots))


DEFAULT_SWEEP_SEEDS: tuple[int, ...] = tuple(range(20))


@dataclass(frozen=True, eq=False)
class SeedSweep(_NanSafeEquality):
    """One comparison's outcome over many seeds - what the gate/marginal/divergent policy is judged on.
    A seed where the comparison was not computable counts in not_computable, never as a non-rejection."""

    name: str
    policy: str
    n_seeds: int
    rejections: int  # computable seeds on which the KS test rejected at ALPHA
    not_computable: int
    median_p_value: float  # over computable seeds; NaN if there were none
    min_p_value: float
    max_p_value: float


def sweep_seeds(family: "str | GeneratorFamily" = "baseline", n_lots: int = DEFAULT_N_LOTS,
                seeds: Iterable[int] = DEFAULT_SWEEP_SEEDS) -> tuple[SeedSweep, ...]:
    if isinstance(seeds, (str, bytes)) or not isinstance(seeds, Iterable):
        raise TypeError(f"seeds must be an iterable of ints, got {type(seeds).__name__}")
    seeds = [_validate_seed(seed) for seed in seeds]
    if not seeds:
        raise ValueError("need at least one seed to sweep")
    if len(set(seeds)) != len(seeds):
        raise ValueError(f"duplicate seeds {seeds} - a repeated seed would be counted twice")
    runs = [run_realism_comparisons(family, n_lots, seed) for seed in seeds]
    sweeps = []
    for k, first in enumerate(runs[0]):
        p = np.array([run[k].p_value if run[k].computable else math.nan for run in runs])
        finite = p[np.isfinite(p)]
        sweeps.append(SeedSweep(
            name=first.name,
            policy=first.policy,
            n_seeds=len(seeds),
            rejections=int(np.sum(finite < ALPHA)),
            not_computable=int(len(p) - len(finite)),
            median_p_value=float(np.median(finite)) if len(finite) else math.nan,
            min_p_value=float(finite.min()) if len(finite) else math.nan,
            max_p_value=float(finite.max()) if len(finite) else math.nan,
        ))
    return tuple(sweeps)


def _verdict(r: RealismComparison) -> str:
    if not r.computable:
        return "not computable - no usable generator values"
    rejected = r.p_value < ALPHA
    if r.policy == "gate":
        return "rejected - generator differs from reference" if rejected else "not rejected"
    if r.policy == "marginal":
        return "rejected on this seed (marginal)" if rejected else "not rejected on this seed (marginal)"
    return "documented divergence" if rejected else "divergence no longer observed - reclassify"


def format_report(results: Iterable[RealismComparison], sweep: Iterable[SeedSweep] = ()) -> str:
    results, sweep = tuple(results), tuple(sweep)
    lines = [f"Realism validation (E1 step 10) - two-sample KS test (scipy.stats.ks_2samp), alpha = {ALPHA}", ""]
    for r in results:
        excluded = f", {r.generator_excluded} series excluded" if r.generator_excluded else ""
        lines += [
            f"{r.name}  [{r.family}, {r.policy}]  D = {r.ks_statistic:.4f}, p = {r.p_value:.4g}  -> {_verdict(r)}",
            f"    generator: {r.generator_statistic} (n = {r.generator_n}{excluded}, median = {r.generator_median:.4g})",
            f"    reference: {r.reference_source} (n = {r.reference_n}, median = {r.reference_median:.4g})",
            f"    caveat:    {r.caveat}",
        ]
        reason = COMPARISON_POLICY[r.name][1]
        if reason:
            lines.append(f"    policy:    {reason}")
    if sweep:
        lines += ["", f"Seed sweep ({sweep[0].n_seeds} seeds): rejections at alpha = {ALPHA}, and p-value range"]
        for s in sweep:
            not_computable = f", {s.not_computable} not computable" if s.not_computable else ""
            lines.append(f"    {s.name:30s} [{s.policy:9s}] rejected {s.rejections}/{s.n_seeds}{not_computable}, "
                         f"median p = {s.median_p_value:.4g}, min p = {s.min_p_value:.4g}, "
                         f"max p = {s.max_p_value:.4g}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the generator's KS realism validation (E1 step 10).")
    parser.add_argument("--family", default="baseline")
    parser.add_argument("--n-lots", type=int, default=DEFAULT_N_LOTS)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--sweep-seeds", type=int, default=len(DEFAULT_SWEEP_SEEDS),
                        help="also sweep seeds 0..N-1 and report each comparison's rejection rate (0 = skip)")
    args = parser.parse_args(argv)
    # Bad arguments are a usage error (exit 2, message on stderr), not a traceback from deep in the generator.
    if args.n_lots < 1:
        parser.error(f"--n-lots must be >= 1, got {args.n_lots}")
    if args.seed < 0:
        parser.error(f"--seed must be >= 0, got {args.seed}")
    if args.sweep_seeds < 0:
        parser.error(f"--sweep-seeds must be >= 0, got {args.sweep_seeds}")
    try:
        family = resolve_family(args.family)
    except (TypeError, ValueError) as error:
        parser.error(str(error))
    sweep = sweep_seeds(family, args.n_lots, range(args.sweep_seeds)) if args.sweep_seeds > 0 else ()
    print(format_report(run_realism_comparisons(family, args.n_lots, args.seed), sweep))


if __name__ == "__main__":
    main()
