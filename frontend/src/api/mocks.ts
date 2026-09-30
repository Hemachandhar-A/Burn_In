/**
 * Hand-typed stand-ins for routes that are in IMPLEMENTATION_PLAN.md Part 5.6 but not yet in the
 * live OpenAPI schema (or, for `dpa-work-order`/`confirmed-outcome`/`worklist`/
 * `corrective-status`, blocked on Block 4a not being merged yet). Each MOCK_<TypeName> mirrors
 * its contracts.py Pydantic model field for field, and each has an open BLOCKERS.md entry naming
 * the route it stands in for.
 *
 * When a route goes live, the one function that calls its mock is edited to call the generated
 * client, and the mock is deleted here. There is no global mock switch on purpose.
 */
import { ApiError } from './errors'

/* ------------------------------------------------------------------------------------------ *
 * Lot Dashboard + Part Detail (P1.11). Stand in for `GET /lots/{lot_id}`, `GET
 * /parts/{component_id}`, `POST /parts/{component_id}/disposition`,
 * `POST /parts/{component_id}/confirmed-outcome`, `POST /lots/{lot_id}/dpa-work-order` - none are
 * in the live schema (P5.3/P5.5/P5.6/P5.7/P5.8 unmerged; BLOCKERS.md). The response shapes below
 * also carry fields `contracts.py` doesn't have yet (CONTRACT_CHANGES.md, "Lot Dashboard and Part
 * Detail need fields..."), named `TEMP_` rather than `MOCK_` for exactly the fields that are
 * additive over the real contract; every field that does exist on the real Pydantic model keeps
 * that model's own name and type.
 * ------------------------------------------------------------------------------------------ */

type Verdict = 'PASS' | 'WATCH' | 'REJECT'
type LotVerdict =
  'LOT_ON_TRACK' | 'LOT_AT_RISK' | 'STOP_RUN_RECOMMENDED' | 'ACCEPT' | 'HOLD' | 'REJECT'

/** contracts.py `RiskAssessment`, verbatim. */
export interface MOCK_RiskAssessment {
  component_id: string
  lot_id: string
  verdict: Verdict
  module_a_rank: number
  module_b_rank: number
  worst_parameter: string
  module_a_ran: boolean
  module_b_ran: boolean
  predicted_168h: number | null
  actual_168h: number | null
  explanation_sentence: string | null
}

/** contracts.py `LotDisposition`, verbatim. */
export interface MOCK_LotDisposition {
  lot_id: string
  status: 'IN_PROGRESS' | 'COMPLETE'
  pda_result: number
  verdict: LotVerdict
  is_forecast: boolean
}

/**
 * contracts.py `AnalysisResults` (= `LotSummaryResponse`) plus lot metadata it has nowhere to
 * carry today (CONTRACT_CHANGES.md item 1: `manufacturer` has no home in any response contract
 * at all). `part_number`/`manufacturer`/`lot_size` are the `TEMP_` additions.
 */
export interface TEMP_LotSummaryResponse {
  assessments: MOCK_RiskAssessment[]
  disposition: MOCK_LotDisposition
  part_number: string
  manufacturer: string
  lot_size: number
}

/** contracts.py `ModuleAResult`, verbatim. */
export interface MOCK_ModuleAResult {
  component_id: string
  parameter: string
  robust_z: number
  mcd_distance: number | null
  isolation_forest_score: number | null
  ecod_score: number
  explainable_tags: Record<string, boolean>
  direction: 'above_median' | 'below_median'
  severity_tier: 'PASS' | 'REVIEW' | 'REJECT'
  severity_cap_reason: string | null
}

/** contracts.py `ModuleBResult`, verbatim. */
export interface MOCK_ModuleBResult {
  component_id: string
  parameter: string
  predicted_168h: number | null
  interval_lower: number | null
  interval_upper: number | null
  physics_baseline_prediction: number | null
  physics_disagreement_gap: number | null
  drift_rate: number | null
  exceeds_safety_slope: boolean | null
  safety_slope: number | null
  forecast_unavailable: boolean
}

/** contracts.py `DispositionRecord`, verbatim. */
export interface MOCK_DispositionRecord {
  project_id: string
  component_id: string
  account_id: string
  verdict: 'ACCEPT' | 'HOLD' | 'REJECT'
  rationale: string
  timestamp: string
  analysis_run_id: string
}

/** contracts.py `ConfirmedOutcomeRecord`, verbatim. */
export interface MOCK_ConfirmedOutcomeRecord {
  project_id: string
  component_id: string
  account_id: string
  confirmed_outcome: 'Confirmed Good' | 'Confirmed Defective' | 'Unknown'
  note: string | null
  recorded_at: string
  analysis_run_id: string
}

/** contracts.py `DispositionRequest`, verbatim. */
export interface MOCK_DispositionRequest {
  verdict: 'ACCEPT' | 'HOLD' | 'REJECT'
  rationale: string
}

/** contracts.py `ConfirmedOutcomeRequest`, verbatim. */
export interface MOCK_ConfirmedOutcomeRequest {
  confirmed_outcome: 'Confirmed Good' | 'Confirmed Defective' | 'Unknown'
  note?: string | null
}

/**
 * contracts.py `FeatureFrame`, with one deviation: `lot_median_0h`/`lot_median_24h` (the only
 * per-checkpoint values that are scalars rather than dict-keyed) are unified into `lot_median`,
 * keyed the same way as `robust_z`/`elapsed_hours` (CONTRACT_CHANGES.md item 4) - the real
 * `FeatureFrame` has no 96h/168h lot-median field to read from at all.
 */
export interface TEMP_FeatureFrame {
  component_id: string
  lot_id: string
  part_number: string
  parameter: string
  unit: string
  value_0h: number
  value_24h: number
  value_96h: number | null
  value_168h: number | null
  delta_24h: number
  delta_96h: number | null
  delta_168h: number | null
  lot_median: Record<string, number>
  robust_z: Record<string, number>
  lot_size: number
  used_pooled_fallback: boolean
  elapsed_hours: Record<string, number>
}

/** CONTRACT_CHANGES.md item 5: MCD's per-feature Mahalanobis-distance decomposition. */
export interface TEMP_MCDContribution {
  parameter: string
  share_pct: number
}

/** CONTRACT_CHANGES.md item 5: ECOD's per-dimension tail probability. */
export interface TEMP_ECODContribution {
  parameter: string
  tail: 'Right Tail' | 'Left Tail'
  neg_log_p: number
}

/**
 * contracts.py `PartDetailResponse` plus `component_id`/`lot_id`/`verdict` (CONTRACT_CHANGES.md
 * items 2-3), `feature_frame` (item 4) and the two contribution charts (item 5).
 */
export interface TEMP_PartDetailResponse {
  component_id: string
  lot_id: string
  part_number: string
  verdict: Verdict
  module_a: MOCK_ModuleAResult
  module_b: MOCK_ModuleBResult
  explanation_sentence: string
  confidence_qualifier: string
  severity_cap_note: string | null
  unavailable_forecast_note: string | null
  staleness_note: string | null
  disposition_history: MOCK_DispositionRecord[]
  confirmed_outcomes: MOCK_ConfirmedOutcomeRecord[]
  feature_frame: TEMP_FeatureFrame
  mcd_d_squared: number
  mcd_contributions: TEMP_MCDContribution[]
  ecod_o_score: number
  ecod_contributions: TEMP_ECODContribution[]
}

/** contracts.py `DPARecommendation`, verbatim. */
export interface MOCK_DPARecommendation {
  component_id: string
  reason: string
}

/** contracts.py `DPAWorkOrderResponse`, verbatim. */
export interface MOCK_DPAWorkOrderResponse {
  recommendations: MOCK_DPARecommendation[]
}

const MOCK_LATENCY_SHORT_MS = 200

/**
 * Anchor for synthetic *past* records (a disposition or confirmed outcome that already exists,
 * as opposed to one just submitted through the form). Using `Date.now()` there would violate rule
 * 9 (same input, same seed, same output, every time) - the exact same component would show a
 * different "N days ago" timestamp depending on what day the app happens to be opened.
 */
const MOCK_REFERENCE_DATE_MS = Date.parse('2026-09-20T12:00:00Z')

/** deterministic per-string seed (rule 9: same input, same seed, same output). */
function hashSeed(value: string): number {
  let h = 2166136261
  for (let i = 0; i < value.length; i++) {
    h ^= value.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/** mulberry32: a small, fast, deterministic PRNG - not a modeled algorithm, just fixture jitter. */
function mulberry32(seed: number): () => number {
  let a = seed
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

interface ParamSpec {
  name: string
  unit: string
  weight: number
}

const MOCK_PARAMETERS: ParamSpec[] = [
  { name: 'Leakage Current', unit: 'µA', weight: 5 },
  { name: 'Propagation Delay', unit: 'ns', weight: 2 },
  { name: 'Iddq (Standby Current)', unit: 'µA', weight: 2 },
  { name: 'Supply Slew Drift', unit: 'mV/µs', weight: 1 },
]

function pickWeighted<T extends { weight: number }>(pool: T[], rand: () => number): T {
  const total = pool.reduce((sum, p) => sum + p.weight, 0)
  let roll = rand() * total
  for (const item of pool) {
    roll -= item.weight
    if (roll <= 0) return item
  }
  return pool[pool.length - 1]
}

function round(value: number, decimals = 1): number {
  const factor = 10 ** decimals
  return Math.round(value * factor) / factor
}

function componentIds(lotId: string, count: number, lotSize: number): string[] {
  const rand = mulberry32(hashSeed(lotId))
  const chosen = new Set<number>()
  // Capped at lotSize distinct numbers exist to choose from; without this, a caller passing
  // count >= lotSize would spin forever never reaching `count` distinct values.
  const target = Math.min(count, lotSize)
  while (chosen.size < target) {
    chosen.add(1 + Math.floor(rand() * lotSize))
  }
  return [...chosen].sort((a, b) => a - b).map((n) => `DUT-${String(n).padStart(3, '0')}`)
}

/**
 * A component id, deterministic per `seed`, guaranteed not to satisfy `exclude` - used for DPA's
 * "control part from the unflagged population" (E13 step 5), which must be neither an
 * already-flagged component nor one of the other two recommendations already chosen. Scans a
 * deterministically shuffled 1..lotSize once (no risk of the unbounded retry a plain "roll again
 * until it's free" loop would have); if every id in range is excluded, falls back to an id
 * outside the lot entirely (lotSize + 1), which by construction cannot collide.
 */
function pickExcludedComponentId(seed: string, lotSize: number, exclude: Set<string>): string {
  const rand = mulberry32(hashSeed(seed))
  const order = Array.from({ length: lotSize }, (_, i) => i + 1)
  for (let i = order.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1))
    ;[order[i], order[j]] = [order[j], order[i]]
  }
  for (const n of order) {
    const id = `DUT-${String(n).padStart(3, '0')}`
    if (!exclude.has(id)) return id
  }
  return `DUT-${String(lotSize + 1).padStart(3, '0')}`
}

/**
 * `GET /lots/{lot_id}` (P5.3). Deterministic per `lotId`: reloading the same lot always shows the
 * same flagged parts, same PDA, same verdict.
 */
export async function MOCK_getLotSummary(lotId: string): Promise<TEMP_LotSummaryResponse> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_SHORT_MS))
  const rand = mulberry32(hashSeed(lotId))
  const lotSize = 77
  const rolledStatus: 'IN_PROGRESS' | 'COMPLETE' = rand() < 0.65 ? 'COMPLETE' : 'IN_PROGRESS'
  // A P1.12 fixture lot keeps the status and part number its History events describe (e.g.
  // LOT-2024-9230 has only a 0h upload, so it can't be COMPLETE). The roll above still consumes
  // its random number, so every other lot's output is unchanged.
  const fixture = Object.hasOwn(MOCK_FIXTURE_LOTS, lotId) ? MOCK_FIXTURE_LOTS[lotId] : undefined
  const status = fixture?.status ?? rolledStatus
  const flaggedCount = 2 + Math.floor(rand() * 4)
  const ids = componentIds(lotId, flaggedCount, lotSize)

  const assessments: MOCK_RiskAssessment[] = ids.map((componentId) => {
    const param = pickWeighted(MOCK_PARAMETERS, rand)
    const severityRoll = rand()
    const verdict: Verdict = severityRoll < 0.3 ? 'REJECT' : 'WATCH'
    const moduleARan = true
    const moduleBRan = status === 'COMPLETE' || rand() < 0.8
    const predicted168h = moduleBRan ? round(30 + rand() * 40) : null
    const actual168h = status === 'COMPLETE' && rand() < 0.6 ? round(30 + rand() * 40) : null
    return {
      component_id: componentId,
      lot_id: lotId,
      verdict,
      module_a_rank: round(0.4 + rand() * 0.6, 3),
      module_b_rank: round(0.3 + rand() * 0.7, 3),
      worst_parameter: param.name,
      module_a_ran: moduleARan,
      module_b_ran: moduleBRan,
      predicted_168h: predicted168h,
      actual_168h: actual168h,
      explanation_sentence: `${componentId}: ${param.name.toLowerCase()} deviates from lot median beyond the calibrated threshold.`,
    }
  })

  const rejectCount = assessments.filter((a) => a.verdict === 'REJECT').length
  const pdaResult = round(assessments.length / lotSize, 4)
  const disposition: MOCK_LotDisposition =
    status === 'COMPLETE'
      ? {
          lot_id: lotId,
          status,
          pda_result: pdaResult,
          verdict:
            pdaResult > 0.05 || rejectCount > 0
              ? 'REJECT'
              : assessments.length > 0
                ? 'HOLD'
                : 'ACCEPT',
          is_forecast: false,
        }
      : {
          lot_id: lotId,
          status,
          pda_result: pdaResult,
          verdict:
            pdaResult > 0.05
              ? 'STOP_RUN_RECOMMENDED'
              : pdaResult > 0.03
                ? 'LOT_AT_RISK'
                : 'LOT_ON_TRACK',
          is_forecast: true,
        }

  const partNumberSuffix = String((Math.abs(hashSeed(lotId)) % 900) + 100)
  return {
    assessments,
    disposition,
    part_number: fixture?.part_number ?? `AD${partNumberSuffix}-JH`,
    manufacturer: rand() < 0.5 ? 'Analog Devices' : 'Texas Instruments',
    lot_size: lotSize,
  }
}

/** `POST /lots/{lot_id}/dpa-work-order` (P5.8, capa/router.py). Up to 3 recommendations (E13 step 5). */
export async function MOCK_generateDpaWorkOrder(lotId: string): Promise<MOCK_DPAWorkOrderResponse> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_SHORT_MS))
  const summary = await MOCK_getLotSummary(lotId)
  const flaggedIds = new Set(summary.assessments.map((a) => a.component_id))
  const usedIds = new Set<string>()
  const recommendations: MOCK_DPARecommendation[] = []

  const byModuleA = [...summary.assessments].sort((a, b) => b.module_a_rank - a.module_a_rank)
  if (byModuleA[0]) {
    recommendations.push({
      component_id: byModuleA[0].component_id,
      reason: `Highest-severity part in this lot (${byModuleA[0].worst_parameter}).`,
    })
    usedIds.add(byModuleA[0].component_id)
  }

  // Excludes whatever was just picked above, not only the exact first entry - a lot with two
  // parts of identical rank could otherwise recommend the same component_id twice.
  const nearBoundary = [...summary.assessments]
    .filter((a) => !usedIds.has(a.component_id))
    .sort((a, b) => Math.abs(a.module_b_rank - 0.5) - Math.abs(b.module_b_rank - 0.5))[0]
  if (nearBoundary) {
    recommendations.push({
      component_id: nearBoundary.component_id,
      reason: 'Highest-uncertainty part nearest the WATCH/REJECT boundary.',
    })
    usedIds.add(nearBoundary.component_id)
  }

  // A genuine control part: neither already recommended above nor itself one of the lot's
  // flagged components - otherwise "unflagged population" would be false and the work order
  // could list the same component_id twice (a duplicate React key, and a nonsensical DPA order).
  const controlId = pickExcludedComponentId(
    `${lotId}-control`,
    summary.lot_size,
    new Set([...usedIds, ...flaggedIds]),
  )
  recommendations.push({
    component_id: controlId,
    reason: 'Control part from the unflagged population.',
  })
  return { recommendations: recommendations.slice(0, 3) }
}

function severityCapNote(rand: () => number): string | null {
  const roll = rand()
  if (roll < 0.2) {
    return 'Module A raw score flagged REJECT via Isolation Forest cross-lot anomaly, but is capped at WATCH pending explainable corroboration.'
  }
  if (roll < 0.3) {
    return "Module A's deviation is below the lot median; capped under direction-awareness and cannot reach REJECT on this signal alone."
  }
  return null
}

/** `GET /parts/{component_id}` (P5.7, fusion/router.py aggregator). Deterministic per `componentId`. */
export async function MOCK_getPartDetail(
  componentId: string,
  hint?: { lotId?: string; verdict?: Verdict; worstParameter?: string },
): Promise<TEMP_PartDetailResponse> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_SHORT_MS))
  const rand = mulberry32(hashSeed(componentId))
  const param =
    MOCK_PARAMETERS.find((p) => p.name === hint?.worstParameter) ??
    pickWeighted(MOCK_PARAMETERS, rand)
  const lotId = hint?.lotId ?? `LOT-2024-${String(1000 + Math.floor(rand() * 9000))}`
  const partNumber = `AD${Math.floor(100 + rand() * 900)}-JH`
  const verdict: Verdict =
    hint?.verdict ?? (rand() < 0.4 ? 'REJECT' : rand() < 0.7 ? 'WATCH' : 'PASS')

  const lotMedian0h = round(9 + rand() * 2)
  const lotMedian24h = round(9.5 + rand() * 2)
  const lotMedian96h = round(10 + rand() * 2.5)
  const lotMedian168h = round(11 + rand() * 3)

  const severityFactor =
    verdict === 'REJECT' ? 3.5 + rand() * 1.5 : verdict === 'WATCH' ? 1.8 + rand() : 0.3 + rand()
  const value0h = round(lotMedian0h + (rand() - 0.5) * 3)
  const value24h = round(lotMedian24h + severityFactor * (3 + rand() * 2))
  const value96h = round(lotMedian96h + severityFactor * (4 + rand() * 3))
  const value168h = round(lotMedian168h + severityFactor * (5 + rand() * 3))

  const robustZ = {
    '0h': round((value0h - lotMedian0h) / 5, 2),
    '24h': round((value24h - lotMedian24h) / 5, 2),
    '96h': round((value96h - lotMedian96h) / 5, 2),
    '168h': round((value168h - lotMedian168h) / 5, 2),
  }
  const elapsedHours = {
    '0h': 0,
    '24h': round(23.5 + rand()),
    '96h': round(95.5 + rand()),
    '168h': round(167.5 + rand()),
  }

  const unrecognizedParameter = rand() < 0.08
  const physicsBaseline = round(value168h * (0.68 + rand() * 0.08))
  const disagreementGap = round(value168h - physicsBaseline)
  const disagreementPct =
    physicsBaseline > 0 ? round((disagreementGap / physicsBaseline) * 100, 1) : 0
  const safetySlope = round((value168h - value24h) / (167.5 - 23.5) / 1.35, 3)
  const driftRate = round((value168h - value24h) / (167.5 - 23.5), 3)

  const moduleB: MOCK_ModuleBResult = unrecognizedParameter
    ? {
        component_id: componentId,
        parameter: param.name,
        predicted_168h: null,
        interval_lower: null,
        interval_upper: null,
        physics_baseline_prediction: null,
        physics_disagreement_gap: null,
        drift_rate: null,
        exceeds_safety_slope: null,
        safety_slope: null,
        forecast_unavailable: true,
      }
    : {
        component_id: componentId,
        parameter: param.name,
        predicted_168h: value168h,
        interval_lower: round(value168h * 0.94),
        interval_upper: round(value168h * 1.06),
        physics_baseline_prediction: physicsBaseline,
        physics_disagreement_gap: disagreementGap,
        drift_rate: driftRate,
        exceeds_safety_slope: driftRate > safetySlope,
        safety_slope: safetySlope,
        forecast_unavailable: false,
      }

  // Cold-start (no prior lots for this part number): null, per ModuleAResult's own doc comment -
  // and a null score can never itself be one of the "explainable" detectors that corroborated
  // the flag (explainable_tags), so the tag is derived from the score, never rolled separately.
  const isolationForestScore = rand() < 0.15 ? null : round(rand(), 3)
  const moduleA: MOCK_ModuleAResult = {
    component_id: componentId,
    parameter: param.name,
    robust_z: robustZ['24h'],
    mcd_distance: round(15 + rand() * 20),
    isolation_forest_score: isolationForestScore,
    ecod_score: round(0.6 + rand() * 0.39, 3),
    explainable_tags: {
      robust_z: true,
      mcd: true,
      isolation_forest: isolationForestScore !== null && rand() > 0.5,
      ecod: true,
    },
    direction: 'above_median',
    severity_tier: verdict === 'REJECT' ? 'REJECT' : verdict === 'WATCH' ? 'REVIEW' : 'PASS',
    severity_cap_reason: null,
  }

  // Sized off MOCK_PARAMETERS itself, not hardcoded to 4 - a future addition to that list would
  // otherwise silently produce `share_pct: NaN` / a negative `neg_log_p` for the new entry, since
  // a fixed-length literal here wouldn't grow to match a longer parameter pool.
  const contribPool = MOCK_PARAMETERS.filter((p) => p.name !== param.name)
  const allParams = [param, ...contribPool]
  const mcdRaw = allParams.map((_, i) =>
    i === 0 ? 0.3 + rand() * 0.7 : rand() * (0.4 / 2 ** (i - 1)),
  )
  const mcdTotal = mcdRaw.reduce((s, v) => s + v, 0)
  const mcdContributions: TEMP_MCDContribution[] = allParams
    .map((p, i) => ({ parameter: p.name, share_pct: round((mcdRaw[i] / mcdTotal) * 100, 1) }))
    .sort((a, b) => b.share_pct - a.share_pct)

  const ecodContributions: TEMP_ECODContribution[] = allParams.map((p, i) => ({
    parameter: p.name,
    tail: i === allParams.length - 1 ? 'Left Tail' : 'Right Tail',
    neg_log_p: round(
      i === 0 ? 3.5 + rand() * 2 : Math.max(0.05, 1.2 - i * 0.3) * (1 + rand() * 0.5),
      2,
    ),
  }))
  ecodContributions.sort((a, b) => b.neg_log_p - a.neg_log_p)

  // A cap note only makes sense if the fused verdict actually is the capped-down tier (E12 step
  // 2): it says Module A's raw score would have crossed further, but rule 10's fused verdict
  // shown at the top of the screen must still be the (correct) capped one, never REJECT.
  const capNote = verdict === 'WATCH' ? severityCapNote(rand) : null
  if (capNote) moduleA.severity_cap_reason = capNote

  const stale = rand() < 0.25
  const dispositionHistory: MOCK_DispositionRecord[] =
    rand() < 0.5
      ? [
          {
            project_id: `proj-${componentId}`,
            component_id: componentId,
            account_id: rand() < 0.5 ? 'a.sharma' : 'r.mehta',
            verdict: verdict === 'PASS' ? 'ACCEPT' : verdict === 'WATCH' ? 'HOLD' : 'REJECT',
            rationale: 'Signed off against the analysis available at the time.',
            timestamp: new Date(
              MOCK_REFERENCE_DATE_MS - 86_400_000 * (2 + Math.floor(rand() * 5)),
            ).toISOString(),
            analysis_run_id: '02',
          },
        ]
      : []

  const confirmedOutcomes: MOCK_ConfirmedOutcomeRecord[] =
    rand() < 0.25
      ? [
          {
            project_id: `proj-${componentId}`,
            component_id: componentId,
            account_id: 'r.mehta',
            confirmed_outcome: verdict === 'REJECT' ? 'Confirmed Defective' : 'Confirmed Good',
            note: null,
            recorded_at: new Date(MOCK_REFERENCE_DATE_MS - 86_400_000).toISOString(),
            analysis_run_id: '02',
          },
        ]
      : []

  const explanation = unrecognizedParameter
    ? `Part ${componentId}: ${param.name.toLowerCase()} at 24h is ${Math.abs(robustZ['24h'])} robust-σ ${robustZ['24h'] >= 0 ? 'above' : 'below'} lot median (median = ${lotMedian24h} ${param.unit}, value = ${value24h} ${param.unit}). This parameter is outside the trained three - drift prediction unavailable.`
    : `Part ${componentId}: ${param.name.toLowerCase()} at 24h is ${Math.abs(robustZ['24h'])} robust-σ ${robustZ['24h'] >= 0 ? 'above' : 'below'} lot median (median = ${lotMedian24h} ${param.unit}, value = ${value24h} ${param.unit}). Predicted 168h drift ${moduleB.exceeds_safety_slope ? 'exceeds' : 'is within'} the calibrated safety slope by ${Math.abs(disagreementPct)}%. Primary driver: 24h delta.`

  return {
    component_id: componentId,
    lot_id: lotId,
    part_number: partNumber,
    verdict,
    module_a: moduleA,
    module_b: moduleB,
    explanation_sentence: explanation,
    // E4 step 6: derived from the CQR interval width and the physics-vs-model gap - both of
    // which only exist when Module B actually produced a forecast. A part with no forecast has
    // nothing to be confident (or borderline) about; claiming otherwise would be exactly the
    // kind of certainty rule 12 says this project must never claim it doesn't have.
    confidence_qualifier: unrecognizedParameter
      ? 'Not applicable — drift prediction unavailable'
      : Math.abs(disagreementPct) > 25
        ? 'High confidence'
        : 'Borderline — recommend retest',
    severity_cap_note: capNote,
    unavailable_forecast_note: unrecognizedParameter
      ? `${param.name} falls outside the three trained parameters; drift prediction unavailable for this part.`
      : null,
    staleness_note: stale
      ? 'Newer analysis run #03 exists compared to disposition sign-off baseline #02 (Module A re-evaluated with 168h checkpoint readings).'
      : null,
    disposition_history: dispositionHistory,
    confirmed_outcomes: confirmedOutcomes,
    feature_frame: {
      component_id: componentId,
      lot_id: lotId,
      part_number: partNumber,
      parameter: param.name,
      unit: param.unit,
      value_0h: value0h,
      value_24h: value24h,
      value_96h: value96h,
      value_168h: value168h,
      delta_24h: round(value24h - value0h),
      delta_96h: round(value96h - value0h),
      delta_168h: round(value168h - value0h),
      lot_median: {
        '0h': lotMedian0h,
        '24h': lotMedian24h,
        '96h': lotMedian96h,
        '168h': lotMedian168h,
      },
      robust_z: robustZ,
      lot_size: 77,
      used_pooled_fallback: rand() < 0.1,
      elapsed_hours: elapsedHours,
    },
    mcd_d_squared: round(mcdRaw.reduce((s, v) => s + v, 0) * 40, 1),
    mcd_contributions: mcdContributions,
    ecod_o_score: moduleA.ecod_score,
    ecod_contributions: ecodContributions,
  }
}

/** `POST /parts/{component_id}/disposition` (P5.5, identity/router.py). */
export async function MOCK_submitDisposition(
  componentId: string,
  request: MOCK_DispositionRequest,
  accountId: string,
): Promise<MOCK_DispositionRecord> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_SHORT_MS))
  if (request.rationale.trim() === '')
    throw new ApiError(422, ['A technical rationale is required.'])
  return {
    project_id: `proj-${componentId}`,
    component_id: componentId,
    account_id: accountId,
    verdict: request.verdict,
    rationale: request.rationale,
    timestamp: new Date().toISOString(),
    analysis_run_id: '03',
  }
}

/** `POST /parts/{component_id}/confirmed-outcome` (P5.8, capa/router.py). */
export async function MOCK_submitConfirmedOutcome(
  componentId: string,
  request: MOCK_ConfirmedOutcomeRequest,
  accountId: string,
): Promise<MOCK_ConfirmedOutcomeRecord> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_SHORT_MS))
  return {
    project_id: `proj-${componentId}`,
    component_id: componentId,
    account_id: accountId,
    confirmed_outcome: request.confirmed_outcome,
    note: request.note ?? null,
    recorded_at: new Date().toISOString(),
    analysis_run_id: '03',
  }
}

/* ------------------------------------------------------------------------------------------ *
 * Project Browser, History, Settings (P1.12). Stand in for `GET /events`, `GET
 * /disposition-signoffs` (P2, storage/router.py - Lead-approved global routes, not yet built),
 * `GET /settings`, `POST /settings/propose`, `POST /settings/signoff` (P5.5, identity/router.py)
 * and `GET /settings/worklist`, `GET /settings/corrective-status` (P5.8, capa/router.py). None are
 * in the live OpenAPI schema (BLOCKERS.md). `GET /projects` is real and is not mocked here.
 *
 * Unlike the per-id generators above, these share one small fixture world (MOCK_FIXTURE_PROJECTS)
 * so History, the worklist and the Project Browser tell the same story. The settings and event
 * stores are mutable in-memory state, because proposing and signing off a setting has to change
 * what the next `GET /settings` and `GET /events` return, the way the real routes will.
 * ------------------------------------------------------------------------------------------ */

/** contracts.py `EventResponse`, verbatim. `payload` is a dict by design (Part 5.6 note). */
export interface MOCK_EventResponse {
  event_id: string
  project_id: string
  account_id: string
  event_type: 'ingest' | 'checkpoint_add' | 'analysis_run' | 'config_change'
  timestamp: string
  payload: Record<string, unknown>
}

export type MOCK_SettingField =
  'fn_fp_cost_ratio' | 'pda_threshold' | 'confirmed_outcome_fn_ceiling'

/** contracts.py `PendingSettingChange`, verbatim. */
export interface MOCK_PendingSettingChange {
  field: MOCK_SettingField
  proposed_value: number
  proposed_by: string
  signed_off_by: string | null
}

/** contracts.py `SettingsResponse`, verbatim. */
export interface MOCK_SettingsResponse {
  fn_fp_cost_ratio: number
  pda_threshold: number
  confirmed_outcome_fn_ceiling: number
  pending_changes: MOCK_PendingSettingChange[]
}

/** contracts.py `SettingsProposalRequest`, verbatim. */
export interface MOCK_SettingsProposalRequest {
  field: MOCK_SettingField
  proposed_value: number
}

/** contracts.py `SettingsSignoffRequest`, verbatim. */
export interface MOCK_SettingsSignoffRequest {
  field: MOCK_SettingField
}

/** contracts.py `WorklistResponse`, verbatim. */
export interface MOCK_WorklistResponse {
  pending: MOCK_DispositionRecord[]
}

/** contracts.py `CorrectiveStatusResponse`, verbatim. */
export interface MOCK_CorrectiveStatusResponse {
  fn_rate: number
  fp_rate: number
  confirmed_outcome_count: number
  status: 'OK' | 'CEILING_EXCEEDED' | 'INSUFFICIENT_DATA'
}

/**
 * The projects the History/worklist fixtures refer to, in contracts.py `ProjectSummary` shape.
 * Not served by any mock - `GET /projects` is real. Exported so a local database can be seeded
 * with the same rows (via storage's `save_project`) when screenshot-verifying, and so tests can
 * answer the real route with them.
 */
export const MOCK_FIXTURE_PROJECTS = [
  {
    project_id: 'proj-LOT-2024-6090',
    lot_id: 'LOT-2024-6090',
    part_number: 'OP27-AZ',
    created_by: 'a.sharma',
    created_at: '2026-09-09T08:10:00Z',
  },
  {
    project_id: 'proj-LOT-2024-7712',
    lot_id: 'LOT-2024-7712',
    part_number: 'LM117-HV',
    created_by: 'r.mehta',
    created_at: '2026-09-10T09:40:00Z',
  },
  {
    project_id: 'proj-LOT-2024-8841',
    lot_id: 'LOT-2024-8841',
    part_number: 'AD590-JH',
    created_by: 'r.mehta',
    created_at: '2026-09-11T09:15:30Z',
  },
  {
    project_id: 'proj-LOT-2024-9104',
    lot_id: 'LOT-2024-9104',
    part_number: 'AD590-JH',
    created_by: 'r.mehta',
    created_at: '2026-09-14T10:05:00Z',
  },
  {
    project_id: 'proj-LOT-2024-9230',
    lot_id: 'LOT-2024-9230',
    part_number: 'DAC8830',
    created_by: 'a.sharma',
    created_at: '2026-09-15T14:32:01Z',
  },
] as const

/** What each fixture lot's History says about it: 168h reached = COMPLETE (E7 step 3). */
const MOCK_FIXTURE_LOTS: Record<
  string,
  { status: 'IN_PROGRESS' | 'COMPLETE'; part_number: string }
> = {
  'LOT-2024-6090': { status: 'COMPLETE', part_number: 'OP27-AZ' },
  'LOT-2024-7712': { status: 'COMPLETE', part_number: 'LM117-HV' },
  'LOT-2024-8841': { status: 'COMPLETE', part_number: 'AD590-JH' },
  'LOT-2024-9104': { status: 'IN_PROGRESS', part_number: 'AD590-JH' },
  'LOT-2024-9230': { status: 'IN_PROGRESS', part_number: 'DAC8830' },
}

type FixtureEvent = Omit<MOCK_EventResponse, 'event_id'>

function ingestEvent(
  project: (typeof MOCK_FIXTURE_PROJECTS)[number],
  componentCount: number,
  checkpointHours: number[],
): FixtureEvent {
  return {
    project_id: project.project_id,
    account_id: project.created_by,
    event_type: 'ingest',
    timestamp: project.created_at,
    payload: {
      lot_id: project.lot_id,
      part_number: project.part_number,
      component_count: componentCount,
      checkpoint_hours: checkpointHours,
    },
  }
}

function event(
  projectId: string,
  accountId: string,
  eventType: MOCK_EventResponse['event_type'],
  timestamp: string,
  payload: Record<string, unknown>,
): FixtureEvent {
  return { project_id: projectId, account_id: accountId, event_type: eventType, timestamp, payload }
}

/**
 * `analysis_run` payloads follow the stored diff's real shape, from storage/repository.py
 * `_diff_analysis_results`: `newly_activated_modules`, `resolved_forecasts`, `verdict_changes`. A
 * project's first run has no prior run to diff against (`diff_vs_prior` is null), so its payload
 * is `{}` here. The other three event types' payloads aren't pinned anywhere yet
 * (CONTRACT_CHANGES.md, P1.12), so the keys used for them here are a proposal, not a contract.
 */
function fixtureEvents(): MOCK_EventResponse[] {
  const [p6090, p7712, p8841, p9104, p9230] = MOCK_FIXTURE_PROJECTS
  const rows: FixtureEvent[] = [
    ingestEvent(p6090, 77, [0, 24]),
    event(p6090.project_id, 'a.sharma', 'analysis_run', '2026-09-09T08:10:04Z', {}),
    ingestEvent(p7712, 77, [0, 24, 96, 168]),
    event(p7712.project_id, 'r.mehta', 'analysis_run', '2026-09-10T09:40:05Z', {}),
    ingestEvent(p8841, 77, [0]),
    event(p8841.project_id, 'r.mehta', 'analysis_run', '2026-09-11T09:15:34Z', {}),
    event(p6090.project_id, 'a.sharma', 'checkpoint_add', '2026-09-11T16:20:00Z', {
      checkpoint_hours: [96, 168],
    }),
    event(p6090.project_id, 'a.sharma', 'analysis_run', '2026-09-11T16:20:06Z', {
      newly_activated_modules: { 'DUT-011': ['module_a'], 'DUT-064': ['module_a'] },
      resolved_forecasts: { 'DUT-064': { predicted: 38.2, actual: 41.7 } },
      verdict_changes: {},
    }),
    event(p8841.project_id, 'a.sharma', 'checkpoint_add', '2026-09-12T14:31:40Z', {
      checkpoint_hours: [24],
    }),
    event(p8841.project_id, 'a.sharma', 'analysis_run', '2026-09-12T14:32:00Z', {
      newly_activated_modules: {
        'DUT-019': ['module_b'],
        'DUT-042': ['module_b'],
        'DUT-055': ['module_b'],
        'DUT-070': ['module_b'],
      },
      resolved_forecasts: {},
      verdict_changes: {},
    }),
    ingestEvent(p9104, 77, [0, 24]),
    event(p9104.project_id, 'r.mehta', 'analysis_run', '2026-09-14T10:05:03Z', {}),
    event(p9104.project_id, 'a.sharma', 'checkpoint_add', '2026-09-14T16:50:12Z', {
      checkpoint_hours: [96],
    }),
    event(p9104.project_id, 'a.sharma', 'analysis_run', '2026-09-14T16:50:15Z', {
      newly_activated_modules: {},
      resolved_forecasts: {},
      verdict_changes: {},
    }),
    event(p8841.project_id, 'r.mehta', 'checkpoint_add', '2026-09-15T11:20:40Z', {
      checkpoint_hours: [96, 168],
    }),
    event(p8841.project_id, 'r.mehta', 'analysis_run', '2026-09-15T11:20:45Z', {
      newly_activated_modules: { 'DUT-019': ['module_a'], 'DUT-042': ['module_a'] },
      resolved_forecasts: { 'DUT-042': { predicted: 61.5, actual: 60.8 } },
      verdict_changes: { 'DUT-019': { from: 'WATCH', to: 'REJECT' } },
    }),
    ingestEvent(p9230, 80, [0]),
    event(p9230.project_id, 'a.sharma', 'analysis_run', '2026-09-15T14:32:04Z', {}),
    // The pending PDA-threshold proposal fixtureSettings() starts with.
    event(p8841.project_id, 'r.mehta', 'config_change', '2026-09-16T15:40:22Z', {
      field: 'pda_threshold',
      stage: 'proposed',
      previous_value: 0.05,
      proposed_value: 0.055,
      proposed_by: 'r.mehta',
      signed_off_by: null,
    }),
  ]
  return rows.map((row, i) => ({ event_id: `evt-${String(i + 1).padStart(4, '0')}`, ...row }))
}

function fixtureSignoffs(): MOCK_DispositionRecord[] {
  return [
    {
      project_id: 'proj-LOT-2024-8841',
      component_id: 'DUT-042',
      account_id: 'a.sharma',
      verdict: 'REJECT',
      rationale: 'Leakage 4.1 robust-σ above lot median at 24h, confirmed at 168h.',
      timestamp: '2026-09-15T12:10:00Z',
      analysis_run_id: 'run-8841-03',
    },
    {
      project_id: 'proj-LOT-2024-8841',
      component_id: 'DUT-042',
      account_id: 'r.mehta',
      verdict: 'REJECT',
      rationale: 'Concur. Predicted drift exceeds the calibrated safety slope.',
      timestamp: '2026-09-15T13:05:00Z',
      analysis_run_id: 'run-8841-03',
    },
    {
      project_id: 'proj-LOT-2024-8841',
      component_id: 'DUT-019',
      account_id: 'r.mehta',
      verdict: 'HOLD',
      rationale: 'Hold for retest after 96h drift acceleration.',
      timestamp: '2026-09-15T13:20:00Z',
      analysis_run_id: 'run-8841-03',
    },
    {
      project_id: 'proj-LOT-2024-7712',
      component_id: 'DUT-081',
      account_id: 'r.mehta',
      verdict: 'ACCEPT',
      rationale: 'Leakage within 1.2 robust-σ of lot median at 168h; drift below the safety slope.',
      timestamp: '2026-09-16T10:02:00Z',
      analysis_run_id: 'run-7712-01',
    },
    {
      project_id: 'proj-LOT-2024-9104',
      component_id: 'DUT-055',
      account_id: 'a.sharma',
      verdict: 'HOLD',
      rationale: 'Borderline 96h reading; retest before 168h.',
      timestamp: '2026-09-19T09:30:00Z',
      analysis_run_id: 'run-9104-02',
    },
  ]
}

function fixtureSettings(): MOCK_SettingsResponse {
  return {
    fn_fp_cost_ratio: 10,
    pda_threshold: 0.05,
    confirmed_outcome_fn_ceiling: 0.05,
    pending_changes: [
      {
        field: 'pda_threshold',
        proposed_value: 0.055,
        proposed_by: 'r.mehta',
        signed_off_by: null,
      },
    ],
  }
}

let mockEvents = fixtureEvents()
let mockSettings = fixtureSettings()

/** Test-only: put the mutable settings/event stores back to their fixture state. */
export function MOCK_resetStores(): void {
  mockEvents = fixtureEvents()
  mockSettings = fixtureSettings()
}

function appendConfigEvent(accountId: string, payload: Record<string, unknown>): void {
  mockEvents.push({
    event_id: `evt-${String(mockEvents.length + 1).padStart(4, '0')}`,
    // `Event.project_id` is a non-null FK, but a config change belongs to no project. Which
    // project_id the real route logs it under is an open question (CONTRACT_CHANGES.md, P1.12).
    project_id: 'proj-LOT-2024-8841',
    account_id: accountId,
    event_type: 'config_change',
    timestamp: new Date().toISOString(),
    payload,
  })
}

/** `GET /events` (P2, storage/router.py). Every event, every project, every account (E6 screen 6). */
export async function MOCK_listEvents(): Promise<MOCK_EventResponse[]> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_SHORT_MS))
  return structuredClone(mockEvents)
}

/** `GET /disposition-signoffs` (P2, storage/router.py). */
export async function MOCK_listDispositionSignoffs(): Promise<MOCK_DispositionRecord[]> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_SHORT_MS))
  return fixtureSignoffs()
}

/** `GET /settings` (P5.5, identity/router.py). */
export async function MOCK_getSettings(): Promise<MOCK_SettingsResponse> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_SHORT_MS))
  return structuredClone(mockSettings)
}

/** Why a proposed value can't be accepted, or null. What the real route should 422 on. */
function proposalProblem(field: MOCK_SettingField, value: number): string | null {
  if (!Number.isFinite(value) || value <= 0) {
    return 'proposed_value: must be a number greater than 0.'
  }
  if (field !== 'fn_fp_cost_ratio' && value > 1) {
    return 'proposed_value: a rate must be a fraction no greater than 1.'
  }
  return null
}

/**
 * `POST /settings/propose` (P5.5). `accountId` stands in for the JWT's account the real route
 * reads via `get_current_account`. One pending change per value at a time.
 */
export async function MOCK_proposeSetting(
  request: MOCK_SettingsProposalRequest,
  accountId: string,
): Promise<MOCK_PendingSettingChange> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_SHORT_MS))
  const problem = proposalProblem(request.field, request.proposed_value)
  if (problem) throw new ApiError(422, [problem])
  if (mockSettings.pending_changes.some((p) => p.field === request.field)) {
    throw new ApiError(409, [
      'A change to this value is already awaiting sign-off. It has to be finalized first.',
    ])
  }
  const pending: MOCK_PendingSettingChange = {
    field: request.field,
    proposed_value: request.proposed_value,
    proposed_by: accountId,
    signed_off_by: null,
  }
  mockSettings.pending_changes.push(pending)
  appendConfigEvent(accountId, {
    field: request.field,
    stage: 'proposed',
    previous_value: mockSettings[request.field],
    proposed_value: request.proposed_value,
    proposed_by: accountId,
    signed_off_by: null,
  })
  return structuredClone(pending)
}

/**
 * `POST /settings/signoff` (P5.5). The second sign-off must come from a different account than
 * the proposer (E10 step 5, the same two-distinct-account rule as REJECT). Finalizing applies the
 * value and clears its pending entry.
 */
export async function MOCK_signoffSetting(
  request: MOCK_SettingsSignoffRequest,
  accountId: string,
): Promise<MOCK_SettingsResponse> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_SHORT_MS))
  const pending = mockSettings.pending_changes.find((p) => p.field === request.field)
  if (!pending) throw new ApiError(404, ['No pending change for this value.'])
  if (pending.proposed_by === accountId) {
    throw new ApiError(403, [
      'The second sign-off has to come from a different account than the one that proposed the change.',
    ])
  }
  const previous = mockSettings[request.field]
  mockSettings[request.field] = pending.proposed_value
  mockSettings.pending_changes = mockSettings.pending_changes.filter((p) => p !== pending)
  appendConfigEvent(accountId, {
    field: request.field,
    stage: 'finalized',
    previous_value: previous,
    proposed_value: pending.proposed_value,
    proposed_by: pending.proposed_by,
    signed_off_by: accountId,
  })
  return structuredClone(mockSettings)
}

/** `GET /settings/worklist` (P5.8). Dispositions with no confirmed outcome yet, one per part. */
export async function MOCK_getWorklist(): Promise<MOCK_WorklistResponse> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_SHORT_MS))
  const latest = new Map<string, MOCK_DispositionRecord>()
  for (const record of fixtureSignoffs()) {
    const key = JSON.stringify([record.project_id, record.component_id])
    const seen = latest.get(key)
    if (!seen || seen.timestamp < record.timestamp) latest.set(key, record)
  }
  return { pending: [...latest.values()] }
}

/** contracts.py `ScreeningConfig.min_confirmed_outcomes_for_ceiling` (E13 step 6). */
const MOCK_MIN_CONFIRMED_OUTCOMES = 10

/**
 * `GET /settings/corrective-status` (P5.8). Recomputed on every call against the current ceiling
 * (E13 step 7: live-computed, never a stored alert), so finalizing a ceiling change moves it.
 */
export async function MOCK_getCorrectiveStatus(): Promise<MOCK_CorrectiveStatusResponse> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_SHORT_MS))
  const fnRate = 0.028
  const count = 14
  return {
    fn_rate: fnRate,
    fp_rate: 0.114,
    confirmed_outcome_count: count,
    status:
      count < MOCK_MIN_CONFIRMED_OUTCOMES
        ? 'INSUFFICIENT_DATA'
        : fnRate > mockSettings.confirmed_outcome_fn_ceiling
          ? 'CEILING_EXCEEDED'
          : 'OK',
  }
}
