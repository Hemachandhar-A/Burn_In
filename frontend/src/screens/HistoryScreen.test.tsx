import { act, fireEvent, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import type { DispositionRecord, EventResponse } from '../api/history'
import { fakeServer, renderWithApi, type FakeReply, type Routes } from '../test-utils'
import { HistoryScreen } from './HistoryScreen'

const PROJECTS = [
  {
    project_id: 'p-8841',
    lot_id: 'LOT-2024-8841',
    part_number: 'AD590-JH',
    created_at: '2026-09-11T09:15:30',
    created_by: 'r.mehta',
  },
]

const EVENTS: EventResponse[] = [
  {
    event_id: 'e1',
    project_id: 'p-8841',
    account_id: 'r.mehta',
    event_type: 'ingest',
    timestamp: '2026-09-11T09:15:30Z',
    payload: {
      lot_id: 'LOT-2024-8841',
      part_number: 'AD590-JH',
      component_count: 77,
      checkpoint_hours: [0],
    },
  },
  {
    event_id: 'e2',
    project_id: 'p-8841',
    account_id: 'r.mehta',
    event_type: 'analysis_run',
    timestamp: '2026-09-11T09:15:34Z',
    payload: {},
  },
  {
    event_id: 'e3',
    project_id: 'p-8841',
    account_id: 'a.sharma',
    event_type: 'checkpoint_add',
    // Naive timestamp, the way SQLite hands back datetime.now(UTC): read as UTC.
    timestamp: '2026-09-15T11:20:40',
    payload: { checkpoint_hours: [96, 168] },
  },
  {
    event_id: 'e4',
    project_id: 'p-8841',
    account_id: 'a.sharma',
    event_type: 'analysis_run',
    timestamp: '2026-09-15T11:20:45Z',
    payload: {
      newly_activated_modules: { 'DUT-042': ['module_a'] },
      resolved_forecasts: { 'DUT-042': { predicted: 61.5, actual: 60.8 } },
      verdict_changes: { 'DUT-019': { from: 'WATCH', to: 'REJECT' } },
    },
  },
  {
    event_id: 'e5',
    project_id: 'p-unknown',
    account_id: 'r.mehta',
    event_type: 'config_change',
    timestamp: '2026-09-16T15:40:22Z',
    payload: {
      field: 'pda_threshold',
      stage: 'proposed',
      previous_value: 0.05,
      proposed_value: 0.055,
      proposed_by: 'r.mehta',
      signed_off_by: null,
    },
  },
  {
    event_id: 'e6',
    project_id: 'p-8841',
    account_id: 'a.sharma',
    event_type: 'config_change',
    timestamp: '2026-09-17T08:00:00Z',
    payload: {
      field: 'fn_fp_cost_ratio',
      stage: 'finalized',
      previous_value: 10,
      proposed_value: 12,
      proposed_by: 'r.mehta',
      signed_off_by: 'a.sharma',
    },
  },
]

const SIGNOFFS: DispositionRecord[] = [
  {
    project_id: 'p-8841',
    component_id: 'DUT-042',
    account_id: 'a.sharma',
    verdict: 'REJECT',
    rationale: 'Leakage 4.1 robust-σ above lot median.',
    timestamp: '2026-09-15T12:10:00Z',
    analysis_run_id: 'run-3',
  },
]

function rows() {
  return screen.getAllByRole('row').slice(1)
}

function routes(
  events: FakeReply | EventResponse[] = EVENTS,
  signoffs: FakeReply | DispositionRecord[] = SIGNOFFS,
  projects: unknown = PROJECTS,
): Routes {
  return {
    'GET /projects': { body: projects },
    'GET /events': Array.isArray(events) ? { body: events } : events,
    'GET /disposition-signoffs': Array.isArray(signoffs) ? { body: signoffs } : signoffs,
  }
}

function server(events?: EventResponse[], signoffs?: DispositionRecord[]) {
  return fakeServer(routes(events, signoffs)).fetch
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('HistoryScreen (E6 screen 6)', () => {
  test('one timeline of events and disposition sign-offs, newest first', async () => {
    renderWithApi(<HistoryScreen />, { fetch: server() })

    await screen.findByText(/dual sign-off completed/i)
    const types = rows().map((r) => within(r).getAllByRole('cell')[2].textContent)
    expect(types).toEqual([
      'Config Change',
      'Config Change',
      'Disposition',
      'Analysis Run',
      'Checkpoint Added',
      'Analysis Run',
      'Ingest',
    ])
    expect(within(rows()[4]).getByText('2026-09-15 11:20:40')).toBeInTheDocument()
    expect(within(rows()[4]).getByText('A. Sharma')).toBeInTheDocument()
  })

  test('shows the same log to both accounts - no filtering by who is signed in', async () => {
    const first = renderWithApi(<HistoryScreen />, { fetch: server() })
    await screen.findByText(/dual sign-off completed/i)
    const asSharma = rows().map((r) => r.textContent)
    first.unmount()

    renderWithApi(<HistoryScreen />, {
      fetch: server(),
      session: { token: 't', accountId: 'r.mehta', role: 'Reliability Engineer' },
    })
    await screen.findByText(/dual sign-off completed/i)
    expect(rows().map((r) => r.textContent)).toEqual(asSharma)
  })

  test('describes each event type from its payload, with the lot resolved via GET /projects', async () => {
    renderWithApi(<HistoryScreen />, { fetch: server() })
    await screen.findByText(/dual sign-off completed/i)

    expect(
      screen.getByText('Lot LOT-2024-8841 ingested (part AD590-JH, 77 components, checkpoints 0h)'),
    ).toBeInTheDocument()
    expect(screen.getByText('Added checkpoints 96h, 168h to LOT-2024-8841')).toBeInTheDocument()
    expect(
      screen.getByText('First analysis run for LOT-2024-8841; no prior run to compare against'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Proposed PDA threshold change 5.0% → 5.5%, awaiting a second sign-off from a different account',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Dual sign-off completed: FN:FP cost ratio 10:1 → 12:1 (proposed by R. Mehta, signed off by A. Sharma)',
      ),
    ).toBeInTheDocument()
  })

  test('a timing_flag event shows its server-provided message', async () => {
    renderWithApi(<HistoryScreen />, {
      fetch: server([
        {
          event_id: 'tf1',
          project_id: 'p-8841',
          account_id: 'a.sharma',
          event_type: 'timing_flag',
          timestamp: '2026-09-18T09:00:00Z',
          payload: { timing_flag: true, message: 'Sign-offs occurred < 2 minutes apart.' },
        },
      ]),
    })

    expect(await screen.findByText('Sign-offs occurred < 2 minutes apart.')).toBeInTheDocument()
    expect(screen.getByText('Timing Flag')).toBeInTheDocument()
  })

  test('a disposition row links the part and shows its verdict and rationale verbatim', async () => {
    renderWithApi(<HistoryScreen />, { fetch: server() })
    await screen.findByText(/dual sign-off completed/i)

    const row = rows()[2]
    expect(within(row).getByRole('link', { name: 'DUT-042' })).toHaveAttribute(
      'href',
      '/parts/DUT-042',
    )
    expect(within(row).getByText('REJECT')).toHaveClass('badge-reject')
    expect(within(row).getByText(/Leakage 4\.1 robust-σ above lot median\./)).toBeInTheDocument()
    expect(within(row).getByText(/run-3/)).toBeInTheDocument()
  })

  test('an analysis run with changes carries its stored diff behind a toggle', async () => {
    renderWithApi(<HistoryScreen />, { fetch: server() })
    await screen.findByText(/dual sign-off completed/i)

    expect(
      screen.getByText(
        'Analysis run for LOT-2024-8841: 1 module activation, 1 forecast resolved, 1 verdict change',
      ),
    ).toBeInTheDocument()
    const toggle = screen.getByRole('button', { name: /stored diff/i })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText(/module activation:/i)).not.toBeInTheDocument()

    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const trace = screen.getByRole('region', { name: /stored diff trace/i })
    expect(
      within(trace)
        .getAllByRole('listitem')
        .map((li) => li.textContent),
    ).toEqual([
      'Module activation: Module A activated for DUT-042',
      'Prediction resolved: DUT-042 168h forecast 61.5 resolved to measured 60.8',
      'Verdict shift: DUT-019 moved from WATCH to REJECT',
    ])
    expect(within(trace).getByText('WATCH')).toHaveClass('badge-watch')
    expect(within(trace).getByText('REJECT')).toHaveClass('badge-reject')

    fireEvent.click(toggle)
    expect(screen.queryByRole('region', { name: /stored diff trace/i })).not.toBeInTheDocument()
  })

  test('an analysis run whose diff is empty says so and has no toggle', async () => {
    renderWithApi(<HistoryScreen />, {
      fetch: server(
        [
          {
            ...EVENTS[3],
            payload: { newly_activated_modules: {}, resolved_forecasts: {}, verdict_changes: {} },
          },
        ],
        [],
      ),
    })

    expect(
      await screen.findByText('Analysis run for LOT-2024-8841: no changes from the prior run'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /stored diff/i })).not.toBeInTheDocument()
  })

  test('an unrecognized payload is listed as-is rather than dropped', async () => {
    renderWithApi(<HistoryScreen />, {
      fetch: server([{ ...EVENTS[0], payload: { source: 'script', rows: 12 } }], []),
    })

    expect(await screen.findByText('source: script; rows: 12')).toBeInTheDocument()
  })

  test('long floats in an event payload, including nested ones, go through the number formatter', async () => {
    renderWithApi(<HistoryScreen />, {
      fetch: server(
        [
          {
            ...EVENTS[0],
            payload: { verdict: 'REJECT', pda_result: 0.06493827160493827, detail: { x: 1.23456789 } },
          },
        ],
        [],
      ),
    })

    expect(
      await screen.findByText('verdict: REJECT; pda_result: 0.0649; detail: {"x":1.2346}'),
    ).toBeInTheDocument()
  })

  test('an unknown project id is shown as the id, not hidden', async () => {
    renderWithApi(<HistoryScreen />, { fetch: server([{ ...EVENTS[2], project_id: 'p-gone' }], []) })

    expect(await screen.findByText('Added checkpoints 96h, 168h to p-gone')).toBeInTheDocument()
  })

  test('the log still renders if GET /projects fails, with project ids in place of lot ids', async () => {
    const { fetch } = fakeServer({
      ...routes([EVENTS[2]], []),
      'GET /projects': { status: 500, body: { detail: 'down' } },
    })
    renderWithApi(<HistoryScreen />, { fetch })

    expect(await screen.findByText('Added checkpoints 96h, 168h to p-8841')).toBeInTheDocument()
  })

  test('a failed log load shows the error and can be retried', async () => {
    let calls = 0
    const { fetch } = fakeServer({
      ...routes(),
      'GET /events': () =>
        ++calls === 1
          ? ({ status: 503, body: { detail: 'event store unavailable' } } as FakeReply)
          : ({ body: EVENTS } as FakeReply),
    })
    renderWithApi(<HistoryScreen />, { fetch })

    expect(await screen.findByText('event store unavailable')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    expect(await screen.findByText(/dual sign-off completed/i)).toBeInTheDocument()
  })

  test('empty log', async () => {
    renderWithApi(<HistoryScreen />, { fetch: server([], []) })
    expect(await screen.findByText(/no events on record yet/i)).toBeInTheDocument()
  })
})

describe('HistoryScreen edge cases (P1.12 review)', () => {
  function run(payload: Record<string, unknown>): EventResponse {
    return { ...EVENTS[3], payload }
  }

  async function openTrace() {
    fireEvent.click(await screen.findByRole('button', { name: /stored diff/i }))
    const trace = screen.getByRole('region', { name: /stored diff trace/i })
    return within(trace)
      .getAllByRole('listitem')
      .map((li) => li.textContent)
  }

  test('a diff sent with empty lists or nulls is still a diff with no changes', async () => {
    renderWithApi(<HistoryScreen />, {
      fetch: server(
        [run({ newly_activated_modules: [], resolved_forecasts: null, verdict_changes: {} })],
        [],
      ),
    })
    expect(
      await screen.findByText('Analysis run for LOT-2024-8841: no changes from the prior run'),
    ).toBeInTheDocument()
  })

  test('a resolved forecast with no prediction on record, float noise, and a missing verdict', async () => {
    const consoleError = vi.spyOn(console, 'error')
    renderWithApi(<HistoryScreen />, {
      fetch: server(
        [
          run({
            newly_activated_modules: { 'DUT-007': ['module_a', 'module_a'] },
            resolved_forecasts: {
              'DUT-007': { predicted: null, actual: 60.80000000000001 },
              'DUT-008': { predicted: 61.49999999999999, actual: 60.8 },
            },
            verdict_changes: { 'DUT-009': { from: 'WATCH' } },
          }),
        ],
        [],
      ),
    })

    expect(await openTrace()).toEqual([
      'Module activation: Module A activated for DUT-007',
      'Module activation: Module A activated for DUT-007',
      'Prediction resolved: DUT-007 had no 168h forecast on record; measured 60.8',
      'Prediction resolved: DUT-008 168h forecast 61.5 resolved to measured 60.8',
      'Verdict shift: DUT-009 moved from WATCH to —',
    ])
    expect(consoleError.mock.calls.some((a) => String(a[0]).includes('same key'))).toBe(false)
  })

  test('a repeated event id renders both rows without a duplicate React key', async () => {
    const consoleError = vi.spyOn(console, 'error')
    renderWithApi(<HistoryScreen />, {
      fetch: server([EVENTS[2], { ...EVENTS[2], timestamp: '2026-09-16T00:00:00Z' }], []),
    })

    await screen.findAllByText('Added checkpoints 96h, 168h to LOT-2024-8841')
    expect(rows()).toHaveLength(2)
    expect(consoleError.mock.calls.some((a) => String(a[0]).includes('same key'))).toBe(false)
  })

  test('timestamps sort by instant across offsets; an unparseable one goes last, shown raw', async () => {
    renderWithApi(<HistoryScreen />, {
      fetch: server(
        [
          { ...EVENTS[2], event_id: 'bad', timestamp: 'garbage' },
          // 06:30Z - older, despite reading "12:00".
          { ...EVENTS[2], event_id: 'offset', timestamp: '2026-09-15T12:00:00+05:30' },
          { ...EVENTS[2], event_id: 'utc', timestamp: '2026-09-15T07:00:00Z' },
        ],
        [],
      ),
    })
    await screen.findAllByText(/added checkpoints/i)

    expect(rows().map((r) => within(r).getAllByRole('cell')[0].textContent)).toEqual([
      '2026-09-15 07:00:00',
      '2026-09-15 06:30:00',
      'garbage',
    ])
  })

  test('a disposition with an empty rationale says so instead of showing empty quotes', async () => {
    renderWithApi(<HistoryScreen />, {
      fetch: server([], [{ ...SIGNOFFS[0], rationale: '  ' }]),
    })
    expect(await screen.findByText('(no rationale recorded)')).toBeInTheDocument()
    expect(screen.queryByText(/“/)).not.toBeInTheDocument()
  })

  test('a failed background refresh keeps the last complete log, flagged as stale', async () => {
    let calls = 0
    const { fetch } = fakeServer({
      ...routes(),
      'GET /events': () =>
        ++calls === 1
          ? ({ body: EVENTS } as FakeReply)
          : ({ status: 503, body: { detail: 'down' } } as FakeReply),
    })
    const { queryClient } = renderWithApi(<HistoryScreen />, { fetch })
    await screen.findByText(/dual sign-off completed/i)

    await act(() => queryClient.refetchQueries({ queryKey: ['events'] }))

    expect(await screen.findByText(/could not refresh the history log/i)).toBeInTheDocument()
    expect(screen.getByText(/dual sign-off completed/i)).toBeInTheDocument()
    expect(screen.queryByText(/could not load the history log/i)).not.toBeInTheDocument()
  })

  test('never shows half a log: events without sign-offs is an error, not a partial list', async () => {
    const { fetch } = fakeServer({
      ...routes(EVENTS, []),
      'GET /disposition-signoffs': { status: 500, body: { detail: 'sign-off store unavailable' } },
    })
    renderWithApi(<HistoryScreen />, { fetch })

    expect(await screen.findByText('sign-off store unavailable')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
