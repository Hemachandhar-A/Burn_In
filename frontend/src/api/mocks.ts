/**
 * Hand-typed stand-ins for routes that are in IMPLEMENTATION_PLAN.md Part 5.6 but not yet in the
 * live OpenAPI schema. Each MOCK_<TypeName> mirrors its contracts.py Pydantic model field for
 * field, and each has an open BLOCKERS.md entry naming the route it stands in for.
 *
 * When a route goes live, the one function that calls its mock (src/api/auth.ts for login) is
 * edited to call the generated client, and the mock is deleted here. There is no global
 * mock switch on purpose.
 */
import { ApiError } from './errors'

/** contracts.py `LoginRequest`. Stands in for `POST /auth/login`'s body (P5.4). */
export interface MOCK_LoginRequest {
  account_id: string
  pin: string
}

/** contracts.py `TokenResponse`. Stands in for `POST /auth/login`'s response (P5.4). */
export interface MOCK_TokenResponse {
  access_token: string
  token_type: 'bearer'
  account_id: string
  role: string
}

/**
 * Demo PINs, read from scripts/seed.py (the same values `seed.py` hashes into the database). They
 * are only here so the mock can reject a wrong PIN and the error state is exercisable. The real
 * check is argon2 on the server (P5.4), and this table is deleted along with the mock.
 */
const MOCK_SEEDED_PINS: Record<string, { pin: string; role: string }> = {
  'a.sharma': { pin: '1234', role: 'Quality Engineer' },
  'r.mehta': { pin: '5678', role: 'Reliability Engineer' },
}

/** Simulated network latency, so loading states render the way they will against the real route. */
const MOCK_LATENCY_MS = 250

/**
 * Behaves like `POST /auth/login` will: a TokenResponse on a matching PIN, a 401 otherwise.
 * The token is not a JWT, only an opaque placeholder. Today's real ingestion routes don't
 * verify it yet (they take `account_id` as a form field until identity/ lands).
 */
export async function MOCK_login(
  request: MOCK_LoginRequest,
  latencyMs = MOCK_LATENCY_MS,
): Promise<MOCK_TokenResponse> {
  await new Promise((resolve) => setTimeout(resolve, latencyMs))
  const account = Object.hasOwn(MOCK_SEEDED_PINS, request.account_id)
    ? MOCK_SEEDED_PINS[request.account_id]
    : undefined
  if (!account || account.pin !== request.pin) {
    throw new ApiError(401, ['Incorrect PIN for this account.'])
  }
  return {
    access_token: `mock-token.${request.account_id}`,
    token_type: 'bearer',
    account_id: request.account_id,
    role: account.role,
  }
}

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
  while (chosen.size < count) {
    chosen.add(1 + Math.floor(rand() * lotSize))
  }
  return [...chosen].sort((a, b) => a - b).map((n) => `DUT-${String(n).padStart(3, '0')}`)
}

/**
 * `GET /lots/{lot_id}` (P5.3). Deterministic per `lotId`: reloading the same lot always shows the
 * same flagged parts, same PDA, same verdict.
 */
export async function MOCK_getLotSummary(lotId: string): Promise<TEMP_LotSummaryResponse> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_SHORT_MS))
  const rand = mulberry32(hashSeed(lotId))
  const lotSize = 77
  const status: 'IN_PROGRESS' | 'COMPLETE' = rand() < 0.65 ? 'COMPLETE' : 'IN_PROGRESS'
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
    part_number: `AD${partNumberSuffix}-JH`,
    manufacturer: rand() < 0.5 ? 'Analog Devices' : 'Texas Instruments',
    lot_size: lotSize,
  }
}

/** `POST /lots/{lot_id}/dpa-work-order` (P5.8, capa/router.py). Up to 3 recommendations (E13 step 5). */
export async function MOCK_generateDpaWorkOrder(lotId: string): Promise<MOCK_DPAWorkOrderResponse> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_SHORT_MS))
  const summary = await MOCK_getLotSummary(lotId)
  const byModuleA = [...summary.assessments].sort((a, b) => b.module_a_rank - a.module_a_rank)
  const recommendations: MOCK_DPARecommendation[] = []
  if (byModuleA[0]) {
    recommendations.push({
      component_id: byModuleA[0].component_id,
      reason: `Highest-severity part in this lot (${byModuleA[0].worst_parameter}).`,
    })
  }
  const nearBoundary = [...summary.assessments].sort(
    (a, b) => Math.abs(a.module_b_rank - 0.5) - Math.abs(b.module_b_rank - 0.5),
  )[0]
  if (nearBoundary && nearBoundary.component_id !== recommendations[0]?.component_id) {
    recommendations.push({
      component_id: nearBoundary.component_id,
      reason: 'Highest-uncertainty part nearest the WATCH/REJECT boundary.',
    })
  }
  const controlId = componentIds(`${lotId}-control`, 1, summary.lot_size)[0]
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
    MOCK_PARAMETERS.find((p) => p.name === hint?.worstParameter) ?? pickWeighted(MOCK_PARAMETERS, rand)
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

  const moduleA: MOCK_ModuleAResult = {
    component_id: componentId,
    parameter: param.name,
    robust_z: robustZ['24h'],
    mcd_distance: round(15 + rand() * 20),
    isolation_forest_score: rand() < 0.15 ? null : round(rand(), 3),
    ecod_score: round(0.6 + rand() * 0.39, 3),
    explainable_tags: {
      robust_z: true,
      mcd: true,
      isolation_forest: rand() > 0.5,
      ecod: true,
    },
    direction: 'above_median',
    severity_tier: verdict === 'REJECT' ? 'REJECT' : verdict === 'WATCH' ? 'REVIEW' : 'PASS',
    severity_cap_reason: null,
  }

  const contribPool = MOCK_PARAMETERS.filter((p) => p.name !== param.name)
  const mcdRaw = [rand() * 0.7 + 0.3, rand() * 0.4, rand() * 0.2, rand() * 0.1]
  const mcdTotal = mcdRaw.reduce((s, v) => s + v, 0)
  const mcdContributions: TEMP_MCDContribution[] = [param, ...contribPool]
    .map((p, i) => ({ parameter: p.name, share_pct: round((mcdRaw[i] / mcdTotal) * 100, 1) }))
    .sort((a, b) => b.share_pct - a.share_pct)

  const ecodContributions: TEMP_ECODContribution[] = [param, ...contribPool].map((p, i) => ({
    parameter: p.name,
    tail: i === 3 ? 'Left Tail' : 'Right Tail',
    neg_log_p: round(i === 0 ? 3.5 + rand() * 2 : (1.2 - i * 0.3) * (1 + rand() * 0.5), 2),
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
              Date.now() - 86_400_000 * (2 + Math.floor(rand() * 5)),
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
            recorded_at: new Date(Date.now() - 86_400_000).toISOString(),
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
    confidence_qualifier:
      disagreementPct !== 0 && Math.abs(disagreementPct) > 25
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
