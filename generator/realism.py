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

The comparison policy (gate vs. documented divergence) is fixed per comparison in COMPARISON_POLICY and every
comparison is reported, including the ones that diverge.
"""
import argparse
import csv
import numbers
from collections.abc import Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True)
class PowerLawFit:
    exponent: float
    n_points: int
    relative_residuals: np.ndarray  # measured / fitted - 1, per point


def _log_axis_fit(ticks: dict[float, float]) -> tuple[float, float]:
    values, positions = zip(*ticks.items())
    slope, intercept = np.polyfit(positions, np.log10(values), 1)
    return float(slope), float(intercept)


def ljmu_inset_power_law_fit() -> PowerLawFit:
    """Refit the LJMU inset's measured degradation points with a power law, as the paper does, and return
    each point's relative residual around that fit - the reference's noise-to-signal sample."""
    with _INSET_POINTS_CSV.open(newline="") as f:
        rows = [row for row in csv.reader(line for line in f if not line.startswith("#"))][1:]
    px = np.array([[float(x), float(y)] for x, y in rows])
    (xs, xi), (ys, yi) = _log_axis_fit(_INSET_X_TICKS_PT), _log_axis_fit(_INSET_Y_TICKS_PT)
    log_t, log_gd = xs * px[:, 0] + xi, ys * px[:, 1] + yi
    exponent, log_a = np.polyfit(log_t, log_gd, 1)
    residuals = 10 ** (log_gd - (log_a + exponent * log_t)) - 1
    return PowerLawFit(exponent=float(exponent), n_points=len(px), relative_residuals=residuals)


# --- generator-side extraction ---------------------------------------------------------------------

@dataclass(frozen=True)
class GeneratorStatistics:
    """Healthy-part statistics from generated lots, pooled across the three parameters."""

    relative_drift_168h: np.ndarray  # measured value at 168h / measured value at 0h - 1, per part
    drift_exponent_prior: np.ndarray  # the hidden healthy power-law n actually drawn, per part
    drift_exponent_lot_fit: np.ndarray  # n fitted to the lot-median measured drift, per lot
    time_to_knee_lot: np.ndarray  # lot-median drift at the first post-0h read / at 168h, per lot
    noise_to_signal: np.ndarray  # (measured drift - true drift) / true drift, per part and post-0h read
    drift_exponent_per_part_fit: np.ndarray  # n fitted to one part's own measured drift
    checkpoint_hours: tuple[float, ...]
    lot_fits_excluded: int  # lot series with a non-positive median drift (can't be log-fitted)
    part_fits_excluded: int  # part series with any non-positive measured drift


def _fit_exponent(hours: np.ndarray, drift: np.ndarray) -> float | None:
    if not np.all(drift > 0):
        return None
    return float(np.polyfit(np.log(hours), np.log(drift), 1)[0])


def extract_generator_statistics(lots: Sequence[GeneratedLot]) -> GeneratorStatistics:
    """Measured values come from each lot's production-facing dataset; the sidecar is used only to select
    healthy parts, read the hidden drift exponent, and get the noise-free drift the noise is measured against."""
    lots = list(lots)
    if not lots:
        raise ValueError("need at least one generated lot")
    hours = tuple(lots[0].ground_truth.trajectories.checkpoint_hours)
    for lot in lots:
        if not isinstance(lot, GeneratedLot):
            raise TypeError(f"expected GeneratedLot, got {type(lot).__name__}")
        nominal = lot.ground_truth.nominal_checkpoint_hours
        if nominal[0] != 0.0 or nominal[-1] < _FULL_CAMPAIGN_HOURS or len(nominal) < 3:
            raise ValueError(f"lot {lot.dataset.lot_id!r} needs a 0h read, a post-0h read and the full 168h campaign; "
                             f"got nominal checkpoints {nominal}")
        if tuple(lot.ground_truth.trajectories.checkpoint_hours) != hours:
            raise ValueError("all lots must share one checkpoint schedule - the knee reference depends on it")
    post = np.array(hours[1:])

    rel_168, n_prior, n_lot, knee, nsr, n_part = [], [], [], [], [], []
    lot_excluded = part_excluded = 0
    for lot in lots:
        measured: dict[tuple[str, str], dict[float, float]] = {}
        for r in lot.dataset.readings:
            measured.setdefault((r.component_id, r.parameter), {})[r.checkpoint_hour] = r.value
        healthy = [p for p in lot.ground_truth.trajectories.parts if not p.is_defective]
        for name in PARAMETERS:
            lot_drifts = []
            for part in healthy:
                m = np.array([measured[(part.component_id, name)][h] for h in hours])
                true = np.array(part.values[name])
                drift, true_drift = m[1:] - m[0], true[1:] - true[0]
                rel_168.append(m[-1] / m[0] - 1)
                n_prior.append(part.drift_exponent[name])
                nsr.extend((drift - true_drift) / true_drift)
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
        relative_drift_168h=np.array(rel_168),
        drift_exponent_prior=np.array(n_prior),
        drift_exponent_lot_fit=np.array(n_lot),
        time_to_knee_lot=np.array(knee),
        noise_to_signal=np.array(nsr),
        drift_exponent_per_part_fit=np.array(n_part),
        checkpoint_hours=hours,
        lot_fits_excluded=lot_excluded,
        part_fits_excluded=part_excluded,
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


@dataclass(frozen=True)
class RealismComparison:
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
    generator_excluded: int = 0  # generator series that couldn't be log-fitted (non-positive drift)


def _compare(name: str, family: str, generator: np.ndarray, reference: np.ndarray,
             excluded: int = 0) -> RealismComparison:
    if len(generator) == 0:
        raise ValueError(f"{name}: no generator values to compare (all {excluded} series excluded)")
    result = ks_2samp(generator, reference)
    statistic, source, caveat = _DESCRIPTIONS[name]
    return RealismComparison(
        name=name,
        family=family,
        policy=COMPARISON_POLICY[name][0],
        generator_statistic=statistic,
        reference_source=source,
        caveat=caveat,
        generator_n=len(generator),
        reference_n=len(reference),
        generator_median=float(np.median(generator)),
        reference_median=float(np.median(reference)),
        ks_statistic=float(result.statistic),
        p_value=float(result.pvalue),
        generator_excluded=excluded,
    )


def compare_to_references(stats: GeneratorStatistics, family: str) -> tuple[RealismComparison, ...]:
    exponents = literature_drift_exponents()
    t1, t_last = stats.checkpoint_hours[1], stats.checkpoint_hours[-1]
    return (
        _compare("degradation_magnitude_168h", family, stats.relative_drift_168h, latif_168h_relative_changes()),
        _compare("drift_exponent_prior", family, stats.drift_exponent_prior, exponents),
        _compare("drift_exponent_lot_fit", family, stats.drift_exponent_lot_fit, exponents,
                 stats.lot_fits_excluded),
        _compare("time_to_knee_lot", family, stats.time_to_knee_lot, (t1 / t_last) ** exponents,
                 stats.lot_fits_excluded),
        _compare("noise_to_signal_per_part", family, stats.noise_to_signal,
                 ljmu_inset_power_law_fit().relative_residuals),
        _compare("drift_exponent_per_part_fit", family, stats.drift_exponent_per_part_fit, exponents,
                 stats.part_fits_excluded),
    )


def run_realism_comparisons(family: "str | GeneratorFamily" = "baseline", n_lots: int = DEFAULT_N_LOTS,
                            seed: int = 0) -> tuple[RealismComparison, ...]:
    """Generate `n_lots` independent lots (one seed; lot identity is mixed into each lot's draws) on the
    default 0/24/96/168h schedule and compare them against every reference. Deterministic in its inputs."""
    if isinstance(n_lots, bool) or not isinstance(n_lots, numbers.Integral):
        raise TypeError(f"n_lots must be an int, got {type(n_lots).__name__}")
    if n_lots < 1:
        raise ValueError(f"n_lots must be >= 1, got {n_lots}")
    family = resolve_family(family)
    lots = [generate_lot(f"REALISM-{k:03d}", "PN-REALISM", seed, account_id="realism-validation", family=family)
            for k in range(int(n_lots))]
    return compare_to_references(extract_generator_statistics(lots), family.name)


DEFAULT_SWEEP_SEEDS: tuple[int, ...] = tuple(range(20))


@dataclass(frozen=True)
class SeedSweep:
    """One comparison's outcome over many seeds - what the gate/marginal/divergent policy is judged on."""

    name: str
    policy: str
    n_seeds: int
    rejections: int  # seeds on which the KS test rejected at ALPHA
    median_p_value: float
    min_p_value: float
    max_p_value: float


def sweep_seeds(family: "str | GeneratorFamily" = "baseline", n_lots: int = DEFAULT_N_LOTS,
                seeds: Sequence[int] = DEFAULT_SWEEP_SEEDS) -> tuple[SeedSweep, ...]:
    seeds = list(seeds)
    if not seeds:
        raise ValueError("need at least one seed to sweep")
    runs = [run_realism_comparisons(family, n_lots, seed) for seed in seeds]
    sweeps = []
    for k, first in enumerate(runs[0]):
        p = np.array([run[k].p_value for run in runs])
        sweeps.append(SeedSweep(name=first.name, policy=first.policy, n_seeds=len(seeds),
                                rejections=int(np.sum(p < ALPHA)), median_p_value=float(np.median(p)),
                                min_p_value=float(p.min()), max_p_value=float(p.max())))
    return tuple(sweeps)


def _verdict(policy: str, rejected: bool) -> str:
    if policy == "gate":
        return "rejected - generator differs from reference" if rejected else "not rejected"
    if policy == "marginal":
        return "rejected on this seed (marginal)" if rejected else "not rejected on this seed (marginal)"
    return "documented divergence" if rejected else "divergence no longer observed - reclassify"


def format_report(results: Sequence[RealismComparison], sweep: Sequence[SeedSweep] = ()) -> str:
    lines = [f"Realism validation (E1 step 10) - two-sample KS test (scipy.stats.ks_2samp), alpha = {ALPHA}", ""]
    for r in results:
        excluded = f", {r.generator_excluded} series excluded" if r.generator_excluded else ""
        lines += [
            (f"{r.name}  [{r.family}, {r.policy}]  D = {r.ks_statistic:.4f}, p = {r.p_value:.4g}"
            f"  -> {_verdict(r.policy, r.p_value < ALPHA)}"),
            f"    generator: {r.generator_statistic} (n = {r.generator_n}{excluded}, median = {r.generator_median:.4g})",
            f"    reference: {r.reference_source} (n = {r.reference_n}, median = {r.reference_median:.4g})",
            f"    caveat:    {r.caveat}",
        ]
        reason = COMPARISON_POLICY[r.name][1]
        if reason:
            lines.append(f"    policy:    {reason}")
    if sweep:
        lines += ["", f"Seed sweep ({sweep[0].n_seeds} seeds): rejections at alpha = {ALPHA}, and p-value range"]
        lines += [f"    {s.name:30s} [{s.policy:9s}] rejected {s.rejections}/{s.n_seeds}, median p = "
                  f"{s.median_p_value:.4g}, min p = {s.min_p_value:.4g}, max p = {s.max_p_value:.4g}"
                  for s in sweep]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the generator's KS realism validation (E1 step 10).")
    parser.add_argument("--family", default="baseline")
    parser.add_argument("--n-lots", type=int, default=DEFAULT_N_LOTS)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--sweep-seeds", type=int, default=len(DEFAULT_SWEEP_SEEDS),
                        help="also sweep seeds 0..N-1 and report each comparison's rejection rate (0 = skip)")
    args = parser.parse_args(argv)
    sweep = sweep_seeds(args.family, args.n_lots, range(args.sweep_seeds)) if args.sweep_seeds > 0 else ()
    print(format_report(run_realism_comparisons(args.family, args.n_lots, args.seed), sweep))


if __name__ == "__main__":
    main()
