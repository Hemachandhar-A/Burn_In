/**
 * Live smoke test: exercises the app's OWN typed client functions (never a raw fetch, rule 14)
 * against a real running backend. Run with the backend up (default http://localhost:8001 for
 * Block 5B-2's own worktree backend; override with VITE_API_BASE_URL):
 *
 *   npx tsx scripts/smoke_live.ts
 *
 * Not part of `npm test` - this hits a real server and a real (seeded) database, not a fake one.
 */
import { login } from '../src/api/auth'
import { createApiClient } from '../src/api/client'
import { ApiError } from '../src/api/errors'
import { listEvents } from '../src/api/history'
import { generateDpaWorkOrder, getLotSummary } from '../src/api/lotDetail'
import { loadDemoLot, uploadLot, type LotMetadata } from '../src/api/lots'
import { getPartDetail, submitConfirmedOutcome } from '../src/api/parts'
import { getCorrectiveStatus, getSettings, getWorklist } from '../src/api/settings'

const BASE_URL = process.env.VITE_API_BASE_URL || 'http://localhost:8001'

let token: string | null = null
const client = createApiClient({ baseUrl: BASE_URL, getToken: () => token })

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`FAIL: ${message}`)
}

async function step<T>(name: string, run: () => Promise<T>): Promise<T> {
  process.stdout.write(`${name} ... `)
  const result = await run()
  console.log('ok')
  return result
}

async function main() {
  const session = await step('login as a.sharma', () =>
    login(client, { account_id: 'a.sharma', pin: '1234' }),
  )
  assert(session.access_token, 'login response has no access_token')
  assert(session.token_type === 'bearer', 'login response token_type is not "bearer"')
  token = session.access_token
  console.log(`  account_id=${session.account_id} role=${session.role}`)

  const upload = await step('loadDemoLot', () => loadDemoLot(client, session.account_id))
  assert(upload.lot_id, 'loadDemoLot response has no lot_id')
  console.log(`  lot_id=${upload.lot_id} status=${upload.status}`)

  const summary = await step('getLotSummary', () => getLotSummary(client, upload.lot_id))
  assert(summary.assessments.length > 0, 'assessments is empty')
  assert(
    typeof summary.explanation_summary === 'string' && summary.explanation_summary.trim() !== '',
    'explanation_summary is empty',
  )
  console.log(
    `  assessments=${summary.assessments.length} explanation_summary="${summary.explanation_summary}"`,
  )

  const events = await step('listEvents', () => listEvents(client))
  assert(
    events.some((e) => e.event_type === 'analysis_run'),
    'no analysis_run event in the log',
  )
  console.log(`  events=${events.length}`)

  const settings = await step('getSettings', () => getSettings(client))
  assert(typeof settings.pda_threshold === 'number', 'pda_threshold is not a number')
  console.log(
    `  fn_fp_cost_ratio=${settings.fn_fp_cost_ratio} pda_threshold=${settings.pda_threshold} confirmed_outcome_fn_ceiling=${settings.confirmed_outcome_fn_ceiling}`,
  )

  // Block 5B-2 Part 3a: the highest-severity flagged component, and its real Part Detail.
  const flagged = summary.assessments.filter((a) => a.verdict !== 'PASS')
  assert(flagged.length > 0, 'the demo lot has no flagged components')
  const top = flagged.reduce((best, a) => (a.module_a_rank > best.module_a_rank ? a : best))
  console.log(`  highest-severity flagged component: ${top.component_id} (${top.verdict})`)

  const partDetail = await step('getPartDetail (Complete lot, flagged part)', () =>
    getPartDetail(client, top.component_id, upload.lot_id),
  )
  assert(
    partDetail.explanation_sentence.trim() !== '',
    'explanation_sentence is empty for a flagged part',
  )
  assert(partDetail.module_a !== null && partDetail.module_a !== undefined, 'module_a is null for a Complete lot')
  assert(partDetail.module_b !== null && partDetail.module_b !== undefined, 'module_b is null for a Complete lot')
  assert(partDetail.explanation, 'explanation is missing for a flagged part')
  console.log(
    `  explanation: zscore_table=${partDetail.explanation!.zscore_table.length} mcd_contributions=${partDetail.explanation!.mcd_contributions.length} ecod_dimensions=${partDetail.explanation!.ecod_dimensions.length} shap_contributions=${partDetail.explanation!.shap_contributions.length}`,
  )

  // Block 5B-2 Part 3b: a small in-progress lot (0h+24h only) - Module A should not have run.
  const csv = [
    'component_id,parameter,checkpoint_hour,value,unit',
    'c1,iddq,0,1.2,uA',
    'c1,iddq,24,3.5,uA',
    'c2,iddq,0,1.1,uA',
    'c2,iddq,24,1.15,uA',
    '',
  ].join('\n')
  const inProgressMeta: LotMetadata = {
    lot_id: `smoke-inprogress-${Date.now()}`,
    part_number: 'SMOKE-PN',
    manufacturer: 'Smoke Test Fab',
    date_code: '2601',
    test_date: '2026-09-30',
  }
  const file = new File([csv], 'inprogress.csv', { type: 'text/csv' })
  const inProgressUpload = await step('uploadLot (small in-progress lot)', () =>
    uploadLot(client, inProgressMeta, file, session.account_id),
  )
  assert(inProgressUpload.status === 'IN_PROGRESS', `expected IN_PROGRESS, got ${inProgressUpload.status}`)
  console.log(`  lot_id=${inProgressUpload.lot_id} status=${inProgressUpload.status}`)

  const c1Detail = await step("getPartDetail('c1') on the in-progress lot", () =>
    getPartDetail(client, 'c1', inProgressUpload.lot_id),
  )
  assert(c1Detail.module_a === null || c1Detail.module_a === undefined, 'module_a is present on an in-progress lot')
  assert(c1Detail.module_b !== null && c1Detail.module_b !== undefined, 'module_b is missing on an in-progress lot')
  console.log(`  module_a=${c1Detail.module_a ?? 'null'} module_b.parameter=${c1Detail.module_b!.parameter}`)

  // Block 5B-2 Part 3c: submitDisposition stays mocked (CONTRACT_CHANGES.md - the real
  // POST /parts/{component_id}/disposition needs project_id/analysis_run_id query parameters
  // PartDetailResponse gives the frontend no way to obtain), so a real round-trip through
  // disposition_history in a fresh getPartDetail is not possible yet. Skipped, not faked.
  console.log(
    'submitDisposition round-trip ... SKIPPED (submitDisposition is mocked - see CONTRACT_CHANGES.md, ' +
      '"PartDetailResponse gives the frontend no way to call POST /parts/{component_id}/disposition correctly")',
  )

  // Block 5C Part 3a: a real DPA work order on the Complete demo lot.
  const workOrder = await step('generateDpaWorkOrder (Complete lot)', () =>
    generateDpaWorkOrder(client, upload.lot_id),
  )
  assert(
    workOrder.recommendations.length >= 1 && workOrder.recommendations.length <= 3,
    `expected 1-3 recommendations, got ${workOrder.recommendations.length}`,
  )
  for (const rec of workOrder.recommendations) {
    assert(rec.reason.trim() !== '', `recommendation for ${rec.component_id} has an empty reason`)
  }
  console.log(
    `  recommendations=${workOrder.recommendations.map((r) => `${r.component_id} (${r.reason})`).join('; ')}`,
  )

  await step('generateDpaWorkOrder on an in-progress lot returns the 409 path', async () => {
    let caught: unknown
    try {
      await generateDpaWorkOrder(client, inProgressUpload.lot_id)
    } catch (error) {
      caught = error
    }
    assert(caught instanceof ApiError, 'in-progress DPA request did not throw an ApiError')
    assert(
      (caught as ApiError).status === 409,
      `in-progress DPA request gave status ${(caught as ApiError).status}, not 409`,
    )
    console.log(`  409 message: "${(caught as ApiError).messages.join(' ')}"`)
  })

  // Block 5C Part 3b: confirmed outcomes for two different flagged parts.
  const second = flagged.find((a) => a.component_id !== top.component_id)
  assert(second, 'the demo lot has fewer than 2 flagged components')
  const defectiveOutcome = await step(`submitConfirmedOutcome (${top.component_id}, Confirmed Defective)`, () =>
    submitConfirmedOutcome(
      client,
      top.component_id,
      { confirmed_outcome: 'Confirmed Defective', note: 'Smoke test' },
      upload.lot_id,
    ),
  )
  assert(defectiveOutcome.confirmed_outcome === 'Confirmed Defective', 'wrong confirmed_outcome echoed back')

  const goodOutcome = await step(`submitConfirmedOutcome (${second.component_id}, Confirmed Good)`, () =>
    submitConfirmedOutcome(
      client,
      second.component_id,
      { confirmed_outcome: 'Confirmed Good', note: 'Smoke test' },
      upload.lot_id,
    ),
  )
  assert(goodOutcome.confirmed_outcome === 'Confirmed Good', 'wrong confirmed_outcome echoed back')

  const corrective = await step('getCorrectiveStatus', () => getCorrectiveStatus(client))
  assert(corrective.confirmed_outcome_count === 2, `expected count=2, got ${corrective.confirmed_outcome_count}`)
  assert(corrective.status === 'INSUFFICIENT_DATA', `expected INSUFFICIENT_DATA, got ${corrective.status}`)
  console.log(
    `  status=${corrective.status} count=${corrective.confirmed_outcome_count} fn_rate=${corrective.fn_rate ?? 'null'} fp_rate=${corrective.fp_rate ?? 'null'}`,
  )

  const worklist = await step('getWorklist', () => getWorklist(client))
  console.log(
    worklist.pending.length > 0
      ? `  pending=${worklist.pending.length}`
      : '  pending=0 (no dispositions exist yet - dispositions cannot be created from the frontend until Block 5D, since submitDisposition is still mocked)',
  )

  await step('wrong-PIN login returns the 401 path', async () => {
    let caught: unknown
    try {
      await login(client, { account_id: 'a.sharma', pin: '0000' })
    } catch (error) {
      caught = error
    }
    assert(caught instanceof ApiError, 'wrong PIN did not throw an ApiError')
    assert((caught as ApiError).status === 401, `wrong PIN gave status ${(caught as ApiError).status}, not 401`)
  })

  console.log('\nAll smoke checks passed.')
}

main().catch((error) => {
  console.error('\n' + (error instanceof Error ? error.message : String(error)))
  process.exitCode = 1
})
