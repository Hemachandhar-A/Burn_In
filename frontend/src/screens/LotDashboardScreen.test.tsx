import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Link, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { ApiError } from '../api/errors'
import * as lotDetailApi from '../api/lotDetail'
import type { LotSummaryResponse } from '../api/lotDetail'
import { fakeServer, renderWithApi, type FakeReply } from '../test-utils'
import { LotDashboardScreen } from './LotDashboardScreen'

/** `LotDashboardScreen` reads `:lotId` via `useParams`, so it needs an actual matching `<Route>`. */
const routed = () => (
  <Routes>
    <Route path="/lots/:lotId" element={<LotDashboardScreen />} />
    <Route path="/" element={<LotDashboardScreen />} />
  </Routes>
)

/** Jumps between two lot dashboards without unmounting anything outside the `<Routes>`, the same
 * way clicking a nav link or a browser back/forward does - `routed()` alone can't exercise this,
 * since `renderWithApi` mounts it fresh for every test. */
const routedWithNav = (other: string) => (
  <>
    {routed()}
    <Link to={other}>go</Link>
  </>
)

type SummaryOverrides = Partial<Pick<LotSummaryResponse, 'assessments' | 'disposition' | 'insufficient_data_components'>>

const SUMMARY = (overrides: SummaryOverrides = {}): LotSummaryResponse => ({
  module_a_results: {},
  module_b_results: {},
  module_a_cutoffs: {},
  module_b_advisory_notes: {},
  part_explanations: {},
  explanation_summary: '2 of 77 parts flagged, concentrated in leakage current.',
  insufficient_data_components: [],
  assessments: [
    {
      component_id: 'DUT-042',
      lot_id: 'LOT-2024-8841',
      verdict: 'REJECT',
      module_a_rank: 0.9,
      module_b_rank: 0.2,
      worst_parameter: 'Leakage Current',
      module_a_ran: true,
      module_b_ran: false,
      predicted_168h: null,
      actual_168h: null,
      explanation_sentence: null,
    },
    {
      component_id: 'DUT-008',
      lot_id: 'LOT-2024-8841',
      verdict: 'WATCH',
      module_a_rank: 0.1,
      module_b_rank: 0.85,
      worst_parameter: 'Propagation Delay',
      module_a_ran: false,
      module_b_ran: true,
      predicted_168h: 40,
      actual_168h: null,
      explanation_sentence: null,
    },
    {
      component_id: 'DUT-999',
      lot_id: 'LOT-2024-8841',
      verdict: 'PASS',
      module_a_rank: 0.05,
      module_b_rank: 0.05,
      worst_parameter: 'Leakage Current',
      module_a_ran: true,
      module_b_ran: true,
      predicted_168h: 12,
      actual_168h: null,
      explanation_sentence: null,
    },
  ],
  disposition: {
    lot_id: 'LOT-2024-8841',
    status: 'COMPLETE',
    pda_result: 0.0519,
    verdict: 'REJECT',
    is_forecast: false,
  },
  ...overrides,
})

/** A fakeServer route for `GET /lots/{lot_id}` that always answers with `reply`, any lot id. */
function lotSummaryRoute(reply: FakeReply | ((request: Request) => FakeReply | Promise<FakeReply>)) {
  return { 'GET /lots/LOT-2024-8841': reply, 'GET /lots/LOT-OTHER': reply }
}

function setup(path = '/lots/LOT-2024-8841', reply: FakeReply = { body: SUMMARY() }) {
  const server = fakeServer(lotSummaryRoute(reply))
  const view = renderWithApi(routed(), { fetch: server.fetch, path })
  return { ...server, ...view }
}

describe('Lot Dashboard screen (E6 screen 3)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  test('shows a loading state, then the lot summary once the fetch resolves', async () => {
    setup()
    expect(screen.getByText('Loading lot summary…')).toBeInTheDocument()
    await screen.findByText('PDA: 5.19%')
    expect(
      screen.getByText((_, el) => el?.textContent === 'Flagged Parts: 2'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('2 of 77 parts flagged, concentrated in leakage current.'),
    ).toBeInTheDocument()
  })

  test('a failed fetch shows a retry button, which retries', async () => {
    let calls = 0
    const { fetch } = fakeServer(
      lotSummaryRoute(() =>
        ++calls === 1
          ? { status: 404, body: { detail: "no project found for lot 'LOT-2024-8841'" } }
          : { body: SUMMARY() },
      ),
    )
    renderWithApi(routed(), { fetch, path: '/lots/LOT-2024-8841' })
    expect(await screen.findByRole('alert')).toHaveTextContent(
      "no project found for lot 'LOT-2024-8841'",
    )
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByText('PDA: 5.19%')
    expect(calls).toBe(2)
  })

  test('a banner lists components with insufficient data, when any exist', async () => {
    setup('/lots/LOT-2024-8841', {
      body: SUMMARY({ insufficient_data_components: ['C7', 'C9'] }),
    })
    expect(
      await screen.findByText(
        (_, el) =>
          el?.textContent === '2 components have insufficient data and were not analysed: C7, C9',
      ),
    ).toBeInTheDocument()
  })

  test('no banner when every component has enough data', async () => {
    setup()
    await screen.findByText('PDA: 5.19%')
    expect(screen.queryByText(/insufficient data/)).toBeNull()
  })

  test('the two ranked lists are filtered and sorted independently, PASS parts excluded', async () => {
    setup()
    await screen.findByText('PDA: 5.19%')

    const outlierTable = screen.getByRole('table', { name: 'By Outlier Severity' })
    const outlierRows = within(outlierTable)
      .getAllByRole('row')
      .slice(1)
      .map((r) => within(r).getAllByRole('cell')[0].textContent)
    expect(outlierRows).toEqual(['DUT-042'])

    const driftTable = screen.getByRole('table', { name: 'By Drift Risk' })
    const driftRows = within(driftTable)
      .getAllByRole('row')
      .slice(1)
      .map((r) => within(r).getAllByRole('cell')[0].textContent)
    expect(driftRows).toEqual(['DUT-008'])
  })

  test('ranked lists put rank 1 (most severe) first and the highest rank number last', async () => {
    const row = (id: string, a: number, b: number) => ({
      ...SUMMARY().assessments[0],
      component_id: id,
      module_a_rank: a,
      module_b_rank: b,
      module_b_ran: true,
    })
    setup('/lots/LOT-2024-8841', {
      body: SUMMARY({
        assessments: [row('C-3', 3, 2), row('C-1', 1, 3), row('C-2', 2, 1), row('C-0', 2, 1)],
      }),
    })
    await screen.findByText('PDA: 5.19%')
    const ids = (name: string) =>
      within(screen.getByRole('table', { name }))
        .getAllByRole('row')
        .slice(1)
        .map((r) => within(r).getAllByRole('cell')[0].textContent)
    expect(ids('By Outlier Severity')).toEqual(['C-1', 'C-0', 'C-2', 'C-3'])
    expect(ids('By Drift Risk')).toEqual(['C-0', 'C-2', 'C-3', 'C-1'])
  })

  test('an in-progress lot says Module A runs when Complete; a Complete lot with no flags keeps the old text', async () => {
    const inProgress = SUMMARY({
      assessments: [],
      disposition: { ...SUMMARY().disposition, status: 'IN_PROGRESS', is_forecast: true },
    })
    const first = setup('/lots/LOT-2024-8841', { body: inProgress })
    await screen.findByText('Module A runs when the lot is Complete.')
    // Only Module B's panel keeps the old text.
    expect(screen.getAllByText('No parts flagged by this module.')).toHaveLength(1)
    first.unmount()

    setup('/lots/LOT-2024-8841', { body: SUMMARY({ assessments: [] }) })
    await screen.findByText('PDA: 5.19%')
    expect(screen.getAllByText('No parts flagged by this module.')).toHaveLength(2)
    expect(screen.queryByText('Module A runs when the lot is Complete.')).toBeNull()
  })

  test('a ranked-list row links to that component’s Part Detail screen', async () => {
    setup()
    await screen.findByText('PDA: 5.19%')
    const link = screen.getByRole('link', { name: 'DUT-042' })
    expect(link).toHaveAttribute('href', '/parts/DUT-042')
  })

  test('Generate DPA Work Order only appears for a COMPLETE lot, and renders its recommendations', async () => {
    const { fetch, requests } = fakeServer({
      ...lotSummaryRoute({ body: SUMMARY() }),
      'POST /lots/LOT-2024-8841/dpa-work-order': {
        body: {
          recommendations: [
            { component_id: 'DUT-042', reason: 'Highest-severity part in this lot.' },
            { component_id: 'DUT-011', reason: 'Control part from the unflagged population.' },
          ],
        },
      },
    })
    renderWithApi(routed(), { fetch, path: '/lots/LOT-2024-8841' })
    await screen.findByText('PDA: 5.19%')

    const dpaButton = screen.getByRole('button', { name: /generate dpa work order/i })
    fireEvent.click(dpaButton)
    await screen.findByText('Highest-severity part in this lot.')
    expect(requests.some((r) => r.method === 'POST' && r.url.endsWith('/dpa-work-order'))).toBe(
      true,
    )
  })

  test('a 409 from the server (lot not actually Complete) shows its message', async () => {
    const { fetch } = fakeServer({
      ...lotSummaryRoute({ body: SUMMARY() }),
      'POST /lots/LOT-2024-8841/dpa-work-order': {
        status: 409,
        body: { detail: "lot 'LOT-2024-8841' is still IN_PROGRESS - a DPA work order requires a COMPLETE lot" },
      },
    })
    renderWithApi(routed(), { fetch, path: '/lots/LOT-2024-8841' })
    await screen.findByText('PDA: 5.19%')

    fireEvent.click(screen.getByRole('button', { name: /generate dpa work order/i }))
    expect(await screen.findByText(/is still IN_PROGRESS/)).toBeInTheDocument()
  })

  test('Generate DPA Work Order is absent for an In-Progress (forecast) lot', async () => {
    setup(
      '/lots/LOT-2024-8841',
      {
        body: SUMMARY({
          disposition: {
            lot_id: 'LOT-2024-8841',
            status: 'IN_PROGRESS',
            pda_result: 0.01,
            verdict: 'LOT_ON_TRACK',
            is_forecast: true,
          },
        }),
      },
    )
    await screen.findByText('PDA: 1.00%')
    expect(screen.queryByRole('button', { name: /generate dpa work order/i })).toBeNull()
    expect(screen.getByText('LOT ON TRACK')).toBeInTheDocument()
    expect(screen.getByText('Forecast')).toBeInTheDocument()
  })

  test('Generate Report downloads the real POST /lots/{lot_id}/report response', async () => {
    // POST /lots/{lot_id}/report is real (report/router.py, P2); a PDF response, not JSON, so it
    // needs its own Content-Type/Content-Disposition rather than the JSON default.
    const realFetch = vi.fn(async (request: Request) => {
      if (request.method === 'GET' && request.url.endsWith('/lots/LOT-2024-8841')) {
        return new Response(JSON.stringify(SUMMARY()), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      expect(request.method).toBe('POST')
      expect(request.url).toContain('/lots/LOT-2024-8841/report')
      // A plain Uint8Array body, not `new Blob([...])`: jsdom's Blob and Node's Response come
      // from different realms in this test environment, and the two don't interoperate.
      return new Response(new Uint8Array([1, 2, 3]), {
        status: 200,
        headers: {
          'Content-Type': 'application/pdf',
          'Content-Disposition': 'attachment; filename="R-1.pdf"',
        },
      })
    })
    // jsdom has no real createObjectURL; patch the actual URL constructor directly rather than
    // replacing the global (openapi-fetch itself calls `new URL(...)` to resolve the request).
    const createObjectURL = vi.fn(() => 'blob:mock-url')
    const original = { createObjectURL: URL.createObjectURL, revokeObjectURL: URL.revokeObjectURL }
    URL.createObjectURL = createObjectURL
    URL.revokeObjectURL = vi.fn()

    try {
      renderWithApi(routed(), { fetch: realFetch, path: '/lots/LOT-2024-8841' })
      await screen.findByText('PDA: 5.19%')

      fireEvent.click(screen.getByRole('button', { name: /generate report/i }))
      await waitFor(() => expect(createObjectURL).toHaveBeenCalled())
    } finally {
      URL.createObjectURL = original.createObjectURL
      URL.revokeObjectURL = original.revokeObjectURL
    }
  })

  test('no lot selected shows a note instead of crashing', () => {
    const server = fakeServer({})
    renderWithApi(routed(), { fetch: server.fetch, path: '/' })
    expect(screen.getByText('No lot selected.')).toBeInTheDocument()
  })

  test('navigating to a different lot clears a previously generated DPA work order', async () => {
    const server = fakeServer({
      ...lotSummaryRoute((request) => {
        const lotId = request.url.endsWith('LOT-OTHER') ? 'LOT-OTHER' : 'LOT-2024-8841'
        return { body: SUMMARY({ disposition: { ...SUMMARY().disposition, lot_id: lotId } }) }
      }),
      'POST /lots/LOT-2024-8841/dpa-work-order': {
        body: {
          recommendations: [
            { component_id: 'DUT-042', reason: 'Highest-severity part in this lot.' },
          ],
        },
      },
    })
    renderWithApi(routedWithNav('/lots/LOT-OTHER'), {
      fetch: server.fetch,
      path: '/lots/LOT-2024-8841',
    })
    await screen.findByText('PDA: 5.19%')

    fireEvent.click(screen.getByRole('button', { name: /generate dpa work order/i }))
    await screen.findByText('DPA Work Order')

    fireEvent.click(screen.getByRole('link', { name: 'go' }))
    await waitFor(() => expect(screen.getByTestId('route-id')).toHaveTextContent('LOT-OTHER'))
    expect(screen.queryByText('DPA Work Order')).toBeNull()
  })

  test('navigating to a different lot clears a stale Generate Report error from the previous one', async () => {
    vi.spyOn(lotDetailApi, 'downloadReport').mockRejectedValue(new ApiError(404, ['no report yet']))
    const server = fakeServer(
      lotSummaryRoute((request) => {
        const lotId = request.url.endsWith('LOT-OTHER') ? 'LOT-OTHER' : 'LOT-2024-8841'
        return { body: SUMMARY({ disposition: { ...SUMMARY().disposition, lot_id: lotId } }) }
      }),
    )
    renderWithApi(routedWithNav('/lots/LOT-OTHER'), {
      fetch: server.fetch,
      path: '/lots/LOT-2024-8841',
    })
    await screen.findByText('PDA: 5.19%')

    fireEvent.click(screen.getByRole('button', { name: /generate report/i }))
    expect(await screen.findByText('Report generation failed')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('link', { name: 'go' }))
    await waitFor(() => expect(screen.getByTestId('route-id')).toHaveTextContent('LOT-OTHER'))
    expect(screen.queryByText('Report generation failed')).toBeNull()
  })

  describe('lot metadata panel', () => {
    const PROJECT = {
      project_id: 'LOT-2024-8841',
      lot_id: 'LOT-2024-8841',
      part_number: 'AD590-JH',
      created_at: '2026-09-11T09:15:30Z',
      created_by: 'r.mehta',
    }
    const render = (project: FakeReply) => {
      const server = fakeServer({
        ...lotSummaryRoute({ body: SUMMARY() }),
        'GET /projects/LOT-2024-8841': project,
      })
      renderWithApi(routed(), { fetch: server.fetch, path: '/lots/LOT-2024-8841' })
      return server
    }

    test('shows the part number from the project alongside the lot id', async () => {
      render({ body: PROJECT })
      expect(await screen.findByText('AD590-JH')).toBeInTheDocument()
      expect(screen.getByText('Part Number')).toBeInTheDocument()
      expect(screen.getAllByText('LOT-2024-8841').length).toBeGreaterThan(0)
    })

    test('shows manufacturer, date code and test date next to the part number when present', async () => {
      render({
        body: {
          ...PROJECT,
          manufacturer: 'Analog Devices',
          date_code: '2603',
          test_date: '2026-03-14T00:00:00',
        },
      })
      expect(await screen.findByText('Analog Devices')).toBeInTheDocument()
      expect(screen.getByText('Manufacturer')).toBeInTheDocument()
      expect(screen.getByText('2603')).toBeInTheDocument()
      expect(screen.getByText('Date Code')).toBeInTheDocument()
      expect(screen.getByText('2026-03-14')).toBeInTheDocument()
      expect(screen.getByText('Test Date')).toBeInTheDocument()
    })

    test('missing metadata fields are left out, not shown as null or undefined', async () => {
      render({ body: { ...PROJECT, manufacturer: null, date_code: '2603', test_date: null } })
      expect(await screen.findByText('2603')).toBeInTheDocument()
      expect(screen.queryByText('Manufacturer')).toBeNull()
      expect(screen.queryByText('Test Date')).toBeNull()
      expect(document.body.textContent).not.toMatch(/undefined|null/)
    })

    test('no optional metadata at all leaves just the part number', async () => {
      render({ body: PROJECT })
      await screen.findByText('AD590-JH')
      expect(screen.queryByText('Manufacturer')).toBeNull()
      expect(screen.queryByText('Date Code')).toBeNull()
      expect(screen.queryByText('Test Date')).toBeNull()
    })

    test('a project without a part number leaves that field out, with no undefined text', async () => {
      render({ body: { ...PROJECT, part_number: '' } })
      await screen.findByText('PDA: 5.19%')
      expect(screen.queryByText('Part Number')).toBeNull()
      expect(document.body.textContent).not.toMatch(/undefined|null/)
    })

    test('a failed metadata request degrades the panel only; the rest still renders', async () => {
      render({ status: 500, body: { detail: 'boom' } })
      await screen.findByText('PDA: 5.19%')
      expect(screen.queryByText('Part Number')).toBeNull()
      expect(screen.queryByRole('alert')).toBeNull()
      expect(screen.getByText('By Outlier Severity')).toBeInTheDocument()
    })
  })
})
