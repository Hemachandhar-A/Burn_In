/**
 * Live smoke test: exercises the app's OWN typed client functions (never a raw fetch, rule 14)
 * against a real running backend. Run with the backend up on http://localhost:8000:
 *
 *   npx tsx scripts/smoke_live.ts
 *
 * Not part of `npm test` - this hits a real server and a real (seeded) database, not a fake one.
 */
import { login } from '../src/api/auth'
import { createApiClient } from '../src/api/client'
import { ApiError } from '../src/api/errors'
import { listEvents } from '../src/api/history'
import { getLotSummary } from '../src/api/lotDetail'
import { loadDemoLot } from '../src/api/lots'
import { getSettings } from '../src/api/settings'

const BASE_URL = 'http://localhost:8000'

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
