import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Route, Routes, useParams } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import type { LotSummaryResponse } from '../api/lotDetail'
import { fakeServer, renderWithApi, type FakeReply, type Routes as FakeRoutes } from '../test-utils'
import { ProjectBrowserScreen } from './ProjectBrowserScreen'

const PROJECTS = [
  {
    project_id: 'p-1',
    lot_id: 'LOT-B',
    part_number: 'AD590-JH',
    created_at: '2026-09-12T09:00:00',
    created_by: 'a.sharma',
  },
  {
    project_id: 'p-2',
    lot_id: 'LOT-A',
    part_number: 'LM117-HV',
    created_at: '2026-09-14T09:00:00',
    created_by: 'r.mehta',
  },
  {
    project_id: 'p-3',
    lot_id: 'LOT-C',
    part_number: 'DAC8830',
    created_at: '2026-09-10T09:00:00',
    created_by: 'someone.else',
  },
]

function summaryWithStatus(
  lotId: string,
  status: 'IN_PROGRESS' | 'COMPLETE',
): LotSummaryResponse {
  return {
    assessments: [],
    explanation_summary: '',
    insufficient_data_components: [],
    module_a_results: {},
    module_b_results: {},
    module_a_cutoffs: {},
    module_b_advisory_notes: {},
    part_explanations: {},
    disposition: {
      lot_id: lotId,
      status,
      pda_result: 0,
      verdict: status === 'COMPLETE' ? 'ACCEPT' : 'LOT_ON_TRACK',
      is_forecast: status !== 'COMPLETE',
    },
  }
}

/** A `Routes` fixture: `GET /projects` plus one `GET /lots/{lot_id}` per project. */
function serverRoutes(
  projects: readonly { lot_id: string }[],
  statusFor: (lotId: string) => 'IN_PROGRESS' | 'COMPLETE' = () => 'COMPLETE',
): FakeRoutes {
  const routes: FakeRoutes = { 'GET /projects': { body: projects } }
  for (const p of projects) {
    routes[`GET /lots/${p.lot_id}`] = { body: summaryWithStatus(p.lot_id, statusFor(p.lot_id)) }
  }
  return routes
}

/** Succeeds once, then answers `failure` on every later call - for background-refetch tests. */
function onceThen(success: FakeReply, failure: FakeReply): () => FakeReply {
  let calls = 0
  return () => (++calls === 1 ? success : failure)
}

function LotStub() {
  return <p>dashboard for {useParams().lotId}</p>
}

const routed = (
  <Routes>
    <Route path="/" element={<ProjectBrowserScreen />} />
    <Route path="/lots/:lotId" element={<LotStub />} />
  </Routes>
)

function dataRows() {
  return screen.getAllByRole('row').slice(1)
}

function lotOrder() {
  return dataRows().map((row) => within(row).getAllByRole('cell')[0].textContent)
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('ProjectBrowserScreen (E6 screen 5)', () => {
  test('lists every project from the real GET /projects, newest first', async () => {
    const { fetch } = fakeServer(serverRoutes(PROJECTS, (id) => (id === 'LOT-A' ? 'IN_PROGRESS' : 'COMPLETE')))
    renderWithApi(routed, { fetch })

    await screen.findByRole('link', { name: 'LOT-A' })
    expect(lotOrder()).toEqual(['LOT-A', 'LOT-B', 'LOT-C'])
    const first = within(dataRows()[0])
    expect(first.getByText('LM117-HV')).toBeInTheDocument()
    expect(first.getByText('2026-09-14')).toBeInTheDocument()
    // created_by is an account id; shown by display name, falling back to the id itself.
    expect(first.getByText('R. Mehta')).toBeInTheDocument()
    expect(within(dataRows()[2]).getByText('someone.else')).toBeInTheDocument()
  })

  test('status comes from each lot summary and is shown as sent, not relabelled', async () => {
    const { fetch } = fakeServer(serverRoutes(PROJECTS, (id) => (id === 'LOT-A' ? 'IN_PROGRESS' : 'COMPLETE')))
    renderWithApi(routed, { fetch })

    await waitFor(() => expect(within(dataRows()[0]).getByText('IN PROGRESS')).toBeInTheDocument())
    expect(within(dataRows()[1]).getByText('COMPLETE')).toBeInTheDocument()
  })

  test('a lot whose status could not be loaded says so instead of guessing', async () => {
    const routes = serverRoutes(PROJECTS.slice(0, 1))
    routes['GET /lots/LOT-B'] = { status: 500, body: { detail: 'boom' } }
    const { fetch } = fakeServer(routes)
    renderWithApi(routed, { fetch })

    expect(await screen.findByText('Unavailable')).toBeInTheDocument()
  })

  test('opening a project goes to its Lot Dashboard', async () => {
    const { fetch } = fakeServer(serverRoutes(PROJECTS))
    renderWithApi(routed, { fetch })

    fireEvent.click(await screen.findByRole('link', { name: 'LOT-B' }))
    expect(await screen.findByText('dashboard for LOT-B')).toBeInTheDocument()
  })

  test('column headers sort, and announce the sort with aria-sort', async () => {
    const { fetch } = fakeServer(serverRoutes(PROJECTS, (id) => (id === 'LOT-A' ? 'IN_PROGRESS' : 'COMPLETE')))
    renderWithApi(routed, { fetch })
    await screen.findByRole('link', { name: 'LOT-A' })

    const created = screen.getByRole('columnheader', { name: /created date/i })
    expect(created).toHaveAttribute('aria-sort', 'descending')

    fireEvent.click(screen.getByRole('button', { name: /lot id/i }))
    expect(lotOrder()).toEqual(['LOT-A', 'LOT-B', 'LOT-C'])
    expect(screen.getByRole('columnheader', { name: /lot id/i })).toHaveAttribute(
      'aria-sort',
      'ascending',
    )
    expect(created).not.toHaveAttribute('aria-sort')

    fireEvent.click(screen.getByRole('button', { name: /lot id/i }))
    expect(lotOrder()).toEqual(['LOT-C', 'LOT-B', 'LOT-A'])

    fireEvent.click(screen.getByRole('button', { name: /part number/i }))
    expect(lotOrder()).toEqual(['LOT-B', 'LOT-C', 'LOT-A'])

    await waitFor(() => expect(within(dataRows()[0]).getByText('COMPLETE')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /status/i }))
    expect(lotOrder()[0]).not.toBe('LOT-A')
    fireEvent.click(screen.getByRole('button', { name: /status/i }))
    expect(lotOrder()[0]).toBe('LOT-A')
  })

  test('empty state points to Ingest', async () => {
    const { fetch } = fakeServer({ 'GET /projects': { body: [] } })
    renderWithApi(routed, { fetch })

    expect(await screen.findByText(/no projects on record yet/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /ingest/i })).toHaveAttribute('href', '/ingest')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  test('a failed GET /projects shows the server message and can be retried', async () => {
    const routes = serverRoutes(PROJECTS, (id) => (id === 'LOT-A' ? 'IN_PROGRESS' : 'COMPLETE'))
    routes['GET /projects'] = onceThen(
      { status: 500, body: { detail: 'database is locked' } },
      { body: PROJECTS },
    )
    const { fetch } = fakeServer(routes)
    renderWithApi(routed, { fetch })

    expect(await screen.findByText('database is locked')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    expect(await screen.findByRole('link', { name: 'LOT-A' })).toBeInTheDocument()
  })
})

describe('ProjectBrowserScreen edge cases (P1.12 review)', () => {
  const base = PROJECTS[0]

  test('lot ids sort case-insensitively and numerically (LOT-9 before LOT-10)', async () => {
    const projects = [
      { ...base, project_id: 'a', lot_id: 'LOT-10' },
      { ...base, project_id: 'b', lot_id: 'lot-2' },
      { ...base, project_id: 'c', lot_id: 'LOT-9' },
    ]
    const { fetch } = fakeServer(serverRoutes(projects))
    renderWithApi(routed, { fetch })
    await screen.findByRole('link', { name: 'LOT-10' })

    fireEvent.click(screen.getByRole('button', { name: /lot id/i }))
    expect(lotOrder()).toEqual(['lot-2', 'LOT-9', 'LOT-10'])
  })

  test('created dates sort by instant and display in UTC, whatever offset they arrive with', async () => {
    const projects = [
      // 2026-09-14T19:30Z, despite reading "15th".
      { ...base, project_id: 'a', lot_id: 'LOT-OFFSET', created_at: '2026-09-15T01:00:00+05:30' },
      { ...base, project_id: 'b', lot_id: 'LOT-UTC', created_at: '2026-09-14T20:00:00Z' },
    ]
    const { fetch } = fakeServer(serverRoutes(projects))
    renderWithApi(routed, { fetch })
    await screen.findByRole('link', { name: 'LOT-UTC' })

    expect(lotOrder()).toEqual(['LOT-UTC', 'LOT-OFFSET'])
    expect(within(dataRows()[1]).getByText('2026-09-14')).toBeInTheDocument()
  })

  test('a blank creator shows a dash and sorts last', async () => {
    const projects = [
      { ...base, project_id: 'a', lot_id: 'LOT-X', created_by: '' },
      { ...base, project_id: 'b', lot_id: 'LOT-Y', created_by: 'r.mehta' },
    ]
    const { fetch } = fakeServer(serverRoutes(projects))
    renderWithApi(routed, { fetch })
    await screen.findByRole('link', { name: 'LOT-X' })

    fireEvent.click(screen.getByRole('button', { name: /created by/i }))
    expect(lotOrder()).toEqual(['LOT-Y', 'LOT-X'])
    expect(within(dataRows()[1]).getByText('—')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /created by/i }))
    expect(lotOrder()).toEqual(['LOT-Y', 'LOT-X'])
  })

  test('a failed background refresh keeps the list and its statuses, flagged as stale', async () => {
    const routes: FakeRoutes = {
      'GET /projects': onceThen({ body: PROJECTS }, { status: 503, body: { detail: 'down' } }),
    }
    for (const p of PROJECTS) {
      routes[`GET /lots/${p.lot_id}`] = onceThen(
        { body: summaryWithStatus(p.lot_id, p.lot_id === 'LOT-A' ? 'IN_PROGRESS' : 'COMPLETE') },
        { status: 500, body: { detail: 'down' } },
      )
    }
    const { fetch } = fakeServer(routes)
    const { queryClient } = renderWithApi(routed, { fetch })
    await waitFor(() => expect(within(dataRows()[0]).getByText('IN PROGRESS')).toBeInTheDocument())

    await act(() => queryClient.refetchQueries())

    expect(await screen.findByText(/could not refresh projects/i)).toBeInTheDocument()
    expect(screen.queryByText(/could not load projects/i)).not.toBeInTheDocument()
    expect(dataRows()).toHaveLength(3)
    expect(within(dataRows()[0]).getByText('IN PROGRESS')).toBeInTheDocument()
    expect(screen.queryByText('Unavailable')).not.toBeInTheDocument()
  })
})
