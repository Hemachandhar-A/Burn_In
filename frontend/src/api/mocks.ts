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
 * Lot Dashboard's DPA work order, and Part Detail's disposition/confirmed-outcome writes. Stand
 * in for `POST /lots/{lot_id}/dpa-work-order` and `POST /parts/{component_id}/confirmed-outcome`
 * (P5.8, capa/router.py - not merged; BLOCKERS.md) and `POST /parts/{component_id}/disposition`
 * (real route exists, but needs `project_id`/`analysis_run_id` query parameters
 * `PartDetailResponse` gives the frontend no way to obtain - CONTRACT_CHANGES.md, "PartDetailResponse
 * gives the frontend no way to call POST /parts/{component_id}/disposition correctly"). `GET
 * /lots/{lot_id}` and `GET /parts/{component_id}` are both real now (lotDetail.ts, parts.ts); their
 * former `TEMP_`/`MOCK_` response types were deleted in Block 5B-1/5B-2. The response shapes below
 * still carry fields `contracts.py` doesn't have yet (CONTRACT_CHANGES.md item 1, "manufacturer
 * has no home..."), named `TEMP_` for exactly the fields that are additive over the real contract;
 * every field that does exist on the real Pydantic model keeps that model's own name and type.
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
 * Project Browser worklist and corrective status (P1.12/P5.8, capa/router.py). `GET /events`,
 * `GET /disposition-signoffs`, `GET /settings`, `POST /settings/propose` and
 * `POST /settings/signoff` are all real now (history.ts, settings.ts) - only
 * `GET /settings/worklist` and `GET /settings/corrective-status` remain mocked, blocked on
 * Block 4a not being merged yet (BLOCKERS.md). `GET /projects` is real and is not mocked here.
 *
 * Unlike the per-id generators above, these share one small fixture world (MOCK_FIXTURE_PROJECTS)
 * so the worklist and the Project Browser tell the same story.
 * ------------------------------------------------------------------------------------------ */

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

let mockSettings = fixtureSettings()

/** Test-only: put the mutable settings store back to its fixture state. */
export function MOCK_resetStores(): void {
  mockSettings = fixtureSettings()
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
