import { fireEvent, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import * as historyApi from '../api/history'
import { ApiError } from '../api/errors'
import type { MOCK_DispositionRecord, MOCK_EventResponse } from '../api/mocks'
import { fakeServer, renderWithApi } from '../test-utils'
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

const EVENTS: MOCK_EventResponse[] = [
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

const SIGNOFFS: MOCK_DispositionRecord[] = [
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

function mockLog(events = EVENTS, signoffs = SIGNOFFS) {
  vi.spyOn(historyApi, 'listEvents').mockResolvedValue(events)
  vi.spyOn(historyApi, 'listDispositionSignoffs').mockResolvedValue(signoffs)
}

function server() {
  return fakeServer({ 'GET /projects': { body: PROJECTS } }).fetch
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('HistoryScreen (E6 screen 6)', () => {
  test('one timeline of events and disposition sign-offs, newest first', async () => {
    mockLog()
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
    mockLog()
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
    mockLog()
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

  test('a disposition row links the part and shows its verdict and rationale verbatim', async () => {
    mockLog()
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
    mockLog()
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
    mockLog(
      [
        {
          ...EVENTS[3],
          payload: { newly_activated_modules: {}, resolved_forecasts: {}, verdict_changes: {} },
        },
      ],
      [],
    )
    renderWithApi(<HistoryScreen />, { fetch: server() })

    expect(
      await screen.findByText('Analysis run for LOT-2024-8841: no changes from the prior run'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /stored diff/i })).not.toBeInTheDocument()
  })

  test('an unrecognized payload is listed as-is rather than dropped', async () => {
    mockLog([{ ...EVENTS[0], payload: { source: 'script', rows: 12 } }], [])
    renderWithApi(<HistoryScreen />, { fetch: server() })

    expect(await screen.findByText('source: script; rows: 12')).toBeInTheDocument()
  })

  test('an unknown project id is shown as the id, not hidden', async () => {
    mockLog([{ ...EVENTS[2], project_id: 'p-gone' }], [])
    renderWithApi(<HistoryScreen />, { fetch: server() })

    expect(await screen.findByText('Added checkpoints 96h, 168h to p-gone')).toBeInTheDocument()
  })

  test('the log still renders if GET /projects fails, with project ids in place of lot ids', async () => {
    mockLog([EVENTS[2]], [])
    const { fetch } = fakeServer({ 'GET /projects': { status: 500, body: { detail: 'down' } } })
    renderWithApi(<HistoryScreen />, { fetch })

    expect(await screen.findByText('Added checkpoints 96h, 168h to p-8841')).toBeInTheDocument()
  })

  test('a failed log load shows the error and can be retried', async () => {
    vi.spyOn(historyApi, 'listEvents')
      .mockRejectedValueOnce(new ApiError(503, ['event store unavailable']))
      .mockResolvedValue(EVENTS)
    vi.spyOn(historyApi, 'listDispositionSignoffs').mockResolvedValue(SIGNOFFS)
    renderWithApi(<HistoryScreen />, { fetch: server() })

    expect(await screen.findByText('event store unavailable')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    expect(await screen.findByText(/dual sign-off completed/i)).toBeInTheDocument()
  })

  test('empty log', async () => {
    mockLog([], [])
    renderWithApi(<HistoryScreen />, { fetch: server() })
    expect(await screen.findByText(/no events on record yet/i)).toBeInTheDocument()
  })
})
