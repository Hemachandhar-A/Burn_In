import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { MOCK_FIXTURE_PROJECTS } from '../api/mocks'
import * as settingsApi from '../api/settings'
import { fakeServer, renderWithApi, SIGNED_IN, type FakeReply, type Routes } from '../test-utils'
import { SettingsScreen } from './SettingsScreen'

const R_MEHTA = { token: 't', accountId: 'r.mehta', role: 'Reliability Engineer' }

interface PendingChange {
  field: string
  proposed_value: number
  proposed_by: string
  signed_off_by: string | null
}

interface SettingsState {
  fn_fp_cost_ratio: number
  pda_threshold: number
  confirmed_outcome_fn_ceiling: number
  pending: PendingChange[]
}

/** Maps a request's bearer token to the account id it stands for, mirroring real JWT auth. */
const TOKEN_ACCOUNTS: Record<string, string> = { [SIGNED_IN.token]: SIGNED_IN.accountId, t: 'r.mehta' }

function accountFor(request: Request): string {
  const token = /^Bearer (.+)$/.exec(request.headers.get('Authorization') ?? '')?.[1] ?? ''
  return TOKEN_ACCOUNTS[token] ?? 'unknown'
}

function settingsBody(state: SettingsState) {
  return {
    fn_fp_cost_ratio: state.fn_fp_cost_ratio,
    pda_threshold: state.pda_threshold,
    confirmed_outcome_fn_ceiling: state.confirmed_outcome_fn_ceiling,
    pending_changes: state.pending,
  }
}

/** The old MOCK_getWorklist's fixture dispositions - now just a fakeServer default body, deduped
 * client-side by the screen itself (`worklistRows`), same as the real route's own raw list would
 * be. */
const WORKLIST_FIXTURE = [
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

/** The old MOCK_getCorrectiveStatus's fixture values, now a fakeServer default body. */
const CORRECTIVE_STATUS_FIXTURE = {
  fn_rate: 0.028,
  fp_rate: 0.114,
  confirmed_outcome_count: 14,
  status: 'OK',
}

/**
 * A real-ish in-memory `/settings` + `/settings/propose` + `/settings/signoff`, matching
 * `identity/router.py`'s actual status codes and detail messages (all 400, not the old mock's
 * 409/403/404), plus default `/settings/worklist` and `/settings/corrective-status` bodies
 * (both real routes now, Block 5C) - tests that care about their content override via `overrides`
 * or spy on `settingsApi.getWorklist`/`getCorrectiveStatus` directly, same as before.
 */
function settingsServer(initial: Partial<SettingsState> = {}, overrides: Routes = {}) {
  const state: SettingsState = {
    fn_fp_cost_ratio: 10,
    pda_threshold: 0.05,
    confirmed_outcome_fn_ceiling: 0.05,
    pending: [
      { field: 'pda_threshold', proposed_value: 0.055, proposed_by: 'r.mehta', signed_off_by: null },
    ],
    ...initial,
  }
  const server = fakeServer({
    'GET /projects': { body: MOCK_FIXTURE_PROJECTS },
    'GET /settings': () => ({ body: settingsBody(state) }),
    'POST /settings/propose': async (request: Request): Promise<FakeReply> => {
      const body = (await request.json()) as { field: string; proposed_value: number }
      if (
        body.field === 'confirmed_outcome_fn_ceiling' &&
        !(body.proposed_value > 0 && body.proposed_value <= 1)
      ) {
        return {
          status: 400,
          body: { detail: 'confirmed_outcome_fn_ceiling must be greater than 0 and at most 1' },
        }
      }
      if (state.pending.some((p) => p.field === body.field)) {
        return { status: 400, body: { detail: 'Change already pending for this field' } }
      }
      const pending: PendingChange = {
        field: body.field,
        proposed_value: body.proposed_value,
        proposed_by: accountFor(request),
        signed_off_by: null,
      }
      state.pending.push(pending)
      return { body: pending }
    },
    'POST /settings/signoff': async (request: Request): Promise<FakeReply> => {
      const body = (await request.json()) as { field: string }
      const pending = state.pending.find((p) => p.field === body.field)
      if (!pending) return { status: 400, body: { detail: 'No pending change for this field' } }
      if (pending.proposed_by === accountFor(request)) {
        return {
          status: 400,
          body: {
            detail: 'Dual sign-off requires two distinct account IDs, not two role labels',
          },
        }
      }
      ;(state as unknown as Record<string, number>)[pending.field] = pending.proposed_value
      state.pending = state.pending.filter((p) => p !== pending)
      return { body: settingsBody(state) }
    },
    'GET /settings/worklist': { body: { pending: WORKLIST_FIXTURE } },
    'GET /settings/corrective-status': { body: CORRECTIVE_STATUS_FIXTURE },
    ...overrides,
  })
  return { ...server, state }
}

function card(name: RegExp) {
  return screen.getByRole('region', { name })
}

async function loaded() {
  await screen.findByRole('region', { name: /fn:fp cost ratio/i })
  await within(card(/fn:fp cost ratio/i)).findByText('10:1')
}

/** The JSON body of the most recent request matching `method path`, or undefined. */
async function lastRequestBody(requests: Request[], methodAndPath: string) {
  const match = [...requests]
    .reverse()
    .find((r) => `${r.method} ${new URL(r.url).pathname}` === methodAndPath)
  return match ? ((await match.json()) as unknown) : undefined
}

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('SettingsScreen (E6 screen 7)', () => {
  test('shows the three live values, and a pending change distinct from the finalized one', async () => {
    const { fetch } = settingsServer()
    renderWithApi(<SettingsScreen />, { fetch })
    await loaded()

    expect(within(card(/confirmed-outcome fn ceiling/i)).getByText('5.0%')).toBeInTheDocument()
    const pda = card(/pda threshold/i)
    expect(pda).toHaveClass('is-pending')
    expect(within(pda).getByText('5.0%')).toBeInTheDocument()
    expect(within(pda).getByText('Pending second sign-off')).toBeInTheDocument()
    expect(within(pda).getByText(/proposed 5\.5% by r\. mehta/i)).toBeInTheDocument()
    // No second proposal while one is pending for the same value.
    expect(within(pda).queryByRole('button', { name: /edit/i })).not.toBeInTheDocument()
    expect(card(/fn:fp cost ratio/i)).not.toHaveClass('is-pending')
  })

  test('proposing a ratio change makes it pending, not final, and logs it to History', async () => {
    const { fetch, requests } = settingsServer()
    renderWithApi(<SettingsScreen />, { fetch })
    await loaded()

    const ratio = card(/fn:fp cost ratio/i)
    fireEvent.click(within(ratio).getByRole('button', { name: /edit/i }))
    const input = within(ratio).getByLabelText(/proposed fn:fp cost ratio/i)
    fireEvent.change(input, { target: { value: '12' } })
    fireEvent.click(within(ratio).getByRole('button', { name: /propose/i }))

    expect(await within(ratio).findByText(/proposed 12:1 by a\. sharma/i)).toBeInTheDocument()
    expect(await lastRequestBody(requests, 'POST /settings/propose')).toEqual({
      field: 'fn_fp_cost_ratio',
      proposed_value: 12,
    })
    expect(within(ratio).getByText('10:1')).toBeInTheDocument()
    expect(ratio).toHaveClass('is-pending')
    // The proposer can't also be the second sign-off.
    expect(within(ratio).queryByRole('button', { name: /sign off/i })).not.toBeInTheDocument()
    expect(
      within(ratio).getByText(/needs a second sign-off from a different account/i),
    ).toBeInTheDocument()
  })

  test('a percentage is typed as a percent and sent as a fraction', async () => {
    const { fetch, requests } = settingsServer()
    renderWithApi(<SettingsScreen />, { fetch })
    await loaded()

    const ceiling = card(/confirmed-outcome fn ceiling/i)
    fireEvent.click(within(ceiling).getByRole('button', { name: /edit/i }))
    const input = within(ceiling).getByLabelText(/proposed confirmed-outcome fn ceiling \(%\)/i)
    expect(input).toHaveValue('5')
    fireEvent.change(input, { target: { value: '4.5' } })
    fireEvent.click(within(ceiling).getByRole('button', { name: /propose/i }))

    await waitFor(async () =>
      expect(await lastRequestBody(requests, 'POST /settings/propose')).toEqual({
        field: 'confirmed_outcome_fn_ceiling',
        proposed_value: 0.045,
      }),
    )
  })

  test.each([
    ['abc', /fn:fp cost ratio/i],
    ['0', /fn:fp cost ratio/i],
    ['', /fn:fp cost ratio/i],
    ['150', /confirmed-outcome fn ceiling/i],
    ['-3', /confirmed-outcome fn ceiling/i],
  ])('rejects %j before sending anything', async (value, name) => {
    const { fetch, requests } = settingsServer()
    renderWithApi(<SettingsScreen />, { fetch })
    await loaded()

    const target = card(name)
    fireEvent.click(within(target).getByRole('button', { name: /edit/i }))
    const input = within(target).getByRole('textbox')
    fireEvent.change(input, { target: { value } })
    fireEvent.click(within(target).getByRole('button', { name: /propose/i }))

    expect(await within(target).findByRole('alert')).toBeInTheDocument()
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(requests.some((r) => r.url.endsWith('/settings/propose'))).toBe(false)
  })

  test('cancel closes the form without proposing', async () => {
    const { fetch, requests } = settingsServer()
    renderWithApi(<SettingsScreen />, { fetch })
    await loaded()

    const ratio = card(/fn:fp cost ratio/i)
    fireEvent.click(within(ratio).getByRole('button', { name: /edit/i }))
    fireEvent.click(within(ratio).getByRole('button', { name: /cancel/i }))
    expect(within(ratio).queryByRole('textbox')).not.toBeInTheDocument()
    expect(within(ratio).getByRole('button', { name: /edit/i })).toHaveFocus()
    expect(requests.some((r) => r.url.endsWith('/settings/propose'))).toBe(false)
  })

  test('a different account signs off, and the value becomes final', async () => {
    const { fetch, requests } = settingsServer()
    renderWithApi(<SettingsScreen />, { fetch })
    await loaded()

    const pda = card(/pda threshold/i)
    fireEvent.click(within(pda).getByRole('button', { name: /sign off/i }))

    await waitFor(() => expect(within(pda).getByText('5.5%')).toBeInTheDocument())
    expect(await lastRequestBody(requests, 'POST /settings/signoff')).toEqual({
      field: 'pda_threshold',
    })
    expect(pda).not.toHaveClass('is-pending')
    expect(within(pda).getByRole('button', { name: /edit/i })).toBeInTheDocument()
  })

  test('the proposer sees no sign-off action on their own change', async () => {
    const { fetch } = settingsServer()
    renderWithApi(<SettingsScreen />, { fetch, session: R_MEHTA })
    await loaded()

    const pda = card(/pda threshold/i)
    expect(within(pda).queryByRole('button', { name: /sign off/i })).not.toBeInTheDocument()
    expect(
      within(pda).getByText(/needs a second sign-off from a different account/i),
    ).toBeInTheDocument()
  })

  test('a server rejection is shown on the card it belongs to', async () => {
    const { fetch } = settingsServer(
      {},
      {
        'POST /settings/signoff': {
          status: 403,
          body: { detail: 'The second sign-off has to come from a different account.' },
        },
      },
    )
    renderWithApi(<SettingsScreen />, { fetch })
    await loaded()

    const pda = card(/pda threshold/i)
    fireEvent.click(within(pda).getByRole('button', { name: /sign off/i }))
    expect(
      await within(pda).findByText('The second sign-off has to come from a different account.'),
    ).toBeInTheDocument()
    expect(within(pda).getByText('5.0%')).toBeInTheDocument()
  })

  test('corrective status shows the live FN rate, with the FP rate for context only', async () => {
    const { fetch } = settingsServer()
    renderWithApi(<SettingsScreen />, { fetch })
    const status = await screen.findByRole('region', { name: /corrective feedback status/i })

    await within(status).findByText('2.8%')
    expect(status.querySelector('.corrective-rate')).toHaveTextContent(
      'FN rate 2.8% (N=14 confirmed outcomes)',
    )
    expect(status.querySelector('.corrective-context')).toHaveTextContent(
      'FP rate 11.4%, shown for context only, never a trigger.',
    )
    const current = within(status).getByText('OK', { selector: '.corrective-current' })
    expect(current).toHaveClass('badge-pass')
  })

  test.each([
    ['CEILING_EXCEEDED', 'badge-reject', /above the 5\.0% ceiling/i],
    ['INSUFFICIENT_DATA', 'badge-watch', /fewer than 10 confirmed outcomes/i],
  ] as const)('corrective status %s', async (status, badge, note) => {
    vi.spyOn(settingsApi, 'getCorrectiveStatus').mockResolvedValue({
      fn_rate: 0.08,
      fp_rate: 0.1,
      confirmed_outcome_count: status === 'INSUFFICIENT_DATA' ? 4 : 20,
      status,
    })
    const { fetch } = settingsServer()
    renderWithApi(<SettingsScreen />, { fetch })
    const region = await screen.findByRole('region', { name: /corrective feedback status/i })

    const current = await within(region).findByText(status.replace('_', ' '), {
      selector: '.corrective-current',
    })
    expect(current).toHaveClass(badge)
    expect(await within(region).findByText(note)).toBeInTheDocument()
  })

  test('the worklist lists dispositions awaiting a confirmed outcome, with days pending', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-09-27T14:00:00Z'))
    const { fetch } = settingsServer()
    renderWithApi(<SettingsScreen />, { fetch })
    const worklist = await screen.findByRole('region', { name: /worklist/i })

    const link = await within(worklist).findByRole('link', { name: 'DUT-042' })
    expect(link).toHaveAttribute('href', '/parts/DUT-042')
    const row = link.closest('tr')!
    await within(row).findByText('LOT-2024-8841')
    expect(within(row).getByText('REJECT')).toBeInTheDocument()
    expect(within(row).getByText('12d')).toBeInTheDocument()
    expect(within(worklist).getAllByRole('row')).toHaveLength(5)
  })

  test('an empty worklist says so', async () => {
    vi.spyOn(settingsApi, 'getWorklist').mockResolvedValue({ pending: [] })
    const { fetch } = settingsServer()
    renderWithApi(<SettingsScreen />, { fetch })
    expect(await screen.findByText(/no dispositions are awaiting/i)).toBeInTheDocument()
  })

  test('a failed settings load shows the error and can be retried', async () => {
    let calls = 0
    const { fetch } = settingsServer(
      {},
      {
        'GET /settings': () =>
          ++calls === 1
            ? { status: 500, body: { detail: 'settings store unavailable' } }
            : { body: settingsBody({ fn_fp_cost_ratio: 10, pda_threshold: 0.05, confirmed_outcome_fn_ceiling: 0.05, pending: [] }) },
      },
    )
    renderWithApi(<SettingsScreen />, { fetch })

    expect(await screen.findByText('settings store unavailable')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    await screen.findByRole('region', { name: /fn:fp cost ratio/i })
    await within(card(/fn:fp cost ratio/i)).findByText('10:1')
  })
})

describe('SettingsScreen edge cases (P1.12 review)', () => {
  test('an entry that already carries signed_off_by is finalized, not offered for sign-off', async () => {
    const { fetch } = settingsServer({
      pending: [
        {
          field: 'pda_threshold',
          proposed_value: 0.055,
          proposed_by: 'r.mehta',
          signed_off_by: 'a.sharma',
        },
      ],
    })
    renderWithApi(<SettingsScreen />, { fetch })
    await loaded()

    const pda = card(/pda threshold/i)
    expect(pda).not.toHaveClass('is-pending')
    expect(within(pda).queryByRole('button', { name: /sign off/i })).not.toBeInTheDocument()
    expect(within(pda).getByRole('button', { name: /edit/i })).toBeInTheDocument()
  })

  test('proposing the current value again is refused before sending', async () => {
    const { fetch, requests } = settingsServer()
    renderWithApi(<SettingsScreen />, { fetch })
    await loaded()

    const ratio = card(/fn:fp cost ratio/i)
    fireEvent.click(within(ratio).getByRole('button', { name: /edit/i }))
    fireEvent.change(within(ratio).getByRole('textbox'), { target: { value: '10:1' } })
    fireEvent.click(within(ratio).getByRole('button', { name: /propose/i }))

    expect(await within(ratio).findByRole('alert')).toHaveTextContent(/already the current value/i)
    expect(requests.some((r) => r.url.endsWith('/settings/propose'))).toBe(false)
  })

  test('the unit a value is shown with is accepted as input', async () => {
    const { fetch, requests } = settingsServer()
    renderWithApi(<SettingsScreen />, { fetch })
    await loaded()

    const ceiling = card(/confirmed-outcome fn ceiling/i)
    fireEvent.click(within(ceiling).getByRole('button', { name: /edit/i }))
    fireEvent.change(within(ceiling).getByRole('textbox'), { target: { value: '4.5%' } })
    fireEvent.click(within(ceiling).getByRole('button', { name: /propose/i }))

    await waitFor(async () =>
      expect(await lastRequestBody(requests, 'POST /settings/propose')).toEqual({
        field: 'confirmed_outcome_fn_ceiling',
        proposed_value: 0.045,
      }),
    )
  })

  test('pressing Enter twice while a proposal is in flight sends it once', async () => {
    const { fetch, requests } = settingsServer()
    renderWithApi(<SettingsScreen />, { fetch })
    await loaded()

    const ratio = card(/fn:fp cost ratio/i)
    fireEvent.click(within(ratio).getByRole('button', { name: /edit/i }))
    const input = within(ratio).getByRole('textbox')
    fireEvent.change(input, { target: { value: '12' } })
    const form = input.closest('form')!
    fireEvent.submit(form)
    fireEvent.submit(form)

    await within(ratio).findByText(/proposed 12:1 by a\. sharma/i)
    expect(requests.filter((r) => r.url.endsWith('/settings/propose'))).toHaveLength(1)
  })

  test('a conflict (someone proposed first) refetches, showing their proposal next to the message', async () => {
    const server = settingsServer({ pending: [] })
    renderWithApi(<SettingsScreen />, { fetch: server.fetch })
    await loaded()

    const ratio = card(/fn:fp cost ratio/i)
    fireEvent.click(within(ratio).getByRole('button', { name: /edit/i }))
    fireEvent.change(within(ratio).getByRole('textbox'), { target: { value: '12' } })

    // Another account's proposal lands on the server first, in the background - simulating the
    // real race the 400 "already pending" response protects against.
    server.state.pending.push({
      field: 'fn_fp_cost_ratio',
      proposed_value: 15,
      proposed_by: 'r.mehta',
      signed_off_by: null,
    })
    fireEvent.click(within(ratio).getByRole('button', { name: /propose/i }))

    expect(await within(ratio).findByText(/proposed 15:1 by r\. mehta/i)).toBeInTheDocument()
    expect(
      within(ratio).getByText('Change already pending for this field'),
    ).toBeInTheDocument()
    expect(within(ratio).queryByRole('textbox')).not.toBeInTheDocument()
    expect(within(ratio).getByRole('button', { name: /sign off/i })).toBeInTheDocument()
  })

  test("an open form closes when another account's proposal arrives, and does not reopen later", async () => {
    const { fetch } = settingsServer({ pending: [] })
    const { queryClient } = renderWithApi(<SettingsScreen />, { fetch })
    await loaded()

    const ratio = card(/fn:fp cost ratio/i)
    fireEvent.click(within(ratio).getByRole('button', { name: /edit/i }))
    fireEvent.change(within(ratio).getByRole('textbox'), { target: { value: '99' } })

    const BASE_SETTINGS = {
      fn_fp_cost_ratio: 10,
      pda_threshold: 0.05,
      confirmed_outcome_fn_ceiling: 0.05,
      pending_changes: [] as PendingChange[],
    }
    act(() => {
      queryClient.setQueryData(['settings'], {
        ...BASE_SETTINGS,
        pending_changes: [
          {
            field: 'fn_fp_cost_ratio',
            proposed_value: 15,
            proposed_by: 'r.mehta',
            signed_off_by: null,
          },
        ],
      })
    })
    await waitFor(() => expect(within(ratio).queryByRole('textbox')).not.toBeInTheDocument())
    await within(ratio).findByText(/proposed 15:1 by r\. mehta/i)

    act(() => {
      queryClient.setQueryData(['settings'], { ...BASE_SETTINGS, fn_fp_cost_ratio: 15 })
    })
    await within(ratio).findByText('15:1')
    expect(within(ratio).getByRole('button', { name: /edit/i })).toBeInTheDocument()
    expect(within(ratio).queryByRole('textbox')).not.toBeInTheDocument()
  })

  test('focus follows the card: to the pending note after proposing, to Edit after signing off', async () => {
    const { fetch } = settingsServer()
    renderWithApi(<SettingsScreen />, { fetch })
    await loaded()

    const ratio = card(/fn:fp cost ratio/i)
    fireEvent.click(within(ratio).getByRole('button', { name: /edit/i }))
    fireEvent.change(within(ratio).getByRole('textbox'), { target: { value: '12' } })
    fireEvent.click(within(ratio).getByRole('button', { name: /propose/i }))
    await waitFor(() => expect(document.activeElement).toHaveClass('pending-change'))
    expect(ratio).toContainElement(document.activeElement as HTMLElement)

    const pda = card(/pda threshold/i)
    fireEvent.click(within(pda).getByRole('button', { name: /sign off/i }))
    await waitFor(() => expect(within(pda).getByRole('button', { name: /edit/i })).toHaveFocus())
  })

  test('proposing and signing off a new FN ceiling round-trips through the real routes', async () => {
    // R. Mehta proposes a 2% ceiling...
    const server = settingsServer({ pending: [] })
    const first = renderWithApi(<SettingsScreen />, { fetch: server.fetch, session: R_MEHTA })
    await loaded()
    const mine = card(/confirmed-outcome fn ceiling/i)
    fireEvent.click(within(mine).getByRole('button', { name: /edit/i }))
    fireEvent.change(within(mine).getByRole('textbox'), { target: { value: '2' } })
    fireEvent.click(within(mine).getByRole('button', { name: /propose/i }))
    await within(mine).findByText(/proposed 2\.0% by r\. mehta/i)
    first.unmount()

    // ...and A. Sharma signs it off, against the SAME server state.
    renderWithApi(<SettingsScreen />, { fetch: server.fetch })
    await loaded()
    const ceiling = card(/confirmed-outcome fn ceiling/i)
    fireEvent.click(within(ceiling).getByRole('button', { name: /sign off/i }))

    await waitFor(() => expect(within(ceiling).getByText('2.0%')).toBeInTheDocument())
    expect(server.state.confirmed_outcome_fn_ceiling).toBe(0.02)
    expect(server.state.pending).toHaveLength(0)
  })

  test('the worklist shows one row per part, and survives odd timestamps', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-09-27T14:00:00Z'))
    const consoleError = vi.spyOn(console, 'error')
    const record = {
      project_id: 'proj-LOT-2024-8841',
      component_id: 'DUT-042',
      account_id: 'a.sharma',
      verdict: 'REJECT' as const,
      rationale: 'x',
      timestamp: '2026-09-15T12:10:00Z',
      analysis_run_id: 'run-3',
    }
    vi.spyOn(settingsApi, 'getWorklist').mockResolvedValue({
      pending: [
        // A dual REJECT: two sign-off records for the same part.
        record,
        { ...record, account_id: 'r.mehta', timestamp: '2026-09-15T13:05:00Z' },
        { ...record, component_id: 'DUT-900', timestamp: 'not a date' },
        { ...record, component_id: 'DUT-901', timestamp: '2026-10-30T00:00:00Z' },
      ],
    })
    const { fetch } = settingsServer()
    renderWithApi(<SettingsScreen />, { fetch })
    const worklist = await screen.findByRole('region', { name: /worklist/i })

    await within(worklist).findByRole('link', { name: 'DUT-042' })
    expect(within(worklist).getAllByRole('link', { name: 'DUT-042' })).toHaveLength(1)
    expect(within(worklist).getAllByRole('row')).toHaveLength(4)
    const unparseable = within(worklist).getByRole('link', { name: 'DUT-900' }).closest('tr')!
    expect(within(unparseable).getByText('—')).toBeInTheDocument()
    const future = within(worklist).getByRole('link', { name: 'DUT-901' }).closest('tr')!
    expect(within(future).getByText('0d')).toBeInTheDocument()
    expect(consoleError.mock.calls.some((args) => String(args[0]).includes('same key'))).toBe(false)
  })

  test('a failed background refresh keeps the values on screen and says they may be stale', async () => {
    let calls = 0
    const { fetch } = settingsServer(
      {},
      {
        'GET /settings': () =>
          ++calls === 1
            ? {
                body: settingsBody({
                  fn_fp_cost_ratio: 10,
                  pda_threshold: 0.05,
                  confirmed_outcome_fn_ceiling: 0.05,
                  pending: [
                    { field: 'pda_threshold', proposed_value: 0.055, proposed_by: 'r.mehta', signed_off_by: null },
                  ],
                }),
              }
            : { status: 503, body: { detail: 'down' } },
      },
    )
    const { queryClient } = renderWithApi(<SettingsScreen />, { fetch })
    await loaded()

    await act(() => queryClient.refetchQueries({ queryKey: ['settings'], exact: true }))

    expect(await screen.findByText(/could not refresh settings/i)).toBeInTheDocument()
    expect(within(card(/fn:fp cost ratio/i)).getByText('10:1')).toBeInTheDocument()
    expect(screen.queryByText(/could not load settings/i)).not.toBeInTheDocument()
  })
})
