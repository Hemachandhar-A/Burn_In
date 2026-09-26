import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import * as lotDetailApi from '../api/lotDetail'
import { ApiError } from '../api/errors'
import type { MOCK_DPAWorkOrderResponse, TEMP_LotSummaryResponse } from '../api/mocks'
import { fakeServer, renderWithApi } from '../test-utils'
import { LotDashboardScreen } from './LotDashboardScreen'

/** `LotDashboardScreen` reads `:lotId` via `useParams`, so it needs an actual matching `<Route>`. */
const routed = () => (
  <Routes>
    <Route path="/lots/:lotId" element={<LotDashboardScreen />} />
    <Route path="/" element={<LotDashboardScreen />} />
  </Routes>
)

const SUMMARY = (overrides: Partial<TEMP_LotSummaryResponse> = {}): TEMP_LotSummaryResponse => ({
  part_number: 'AD590-JH',
  manufacturer: 'Analog Devices',
  lot_size: 77,
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

function setup(path = '/lots/LOT-2024-8841') {
  const server = fakeServer({})
  const view = renderWithApi(routed(), { fetch: server.fetch, path })
  return { ...server, ...view }
}

describe('Lot Dashboard screen (E6 screen 3)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  test('shows a loading state, then the lot summary once the fetch resolves', async () => {
    vi.spyOn(lotDetailApi, 'getLotSummary').mockResolvedValue(SUMMARY())
    setup()
    expect(screen.getByText('Loading lot summary…')).toBeInTheDocument()
    await screen.findByText('AD590-JH')
    expect(screen.getByText('Analog Devices')).toBeInTheDocument()
    expect(screen.getByText('PDA: 5.19%')).toBeInTheDocument()
    expect(
      screen.getByText((_, el) => el?.textContent === 'Flagged Parts: 2 of 77'),
    ).toBeInTheDocument()
  })

  test('a failed fetch shows a retry button, which retries', async () => {
    const getLotSummary = vi
      .spyOn(lotDetailApi, 'getLotSummary')
      .mockRejectedValueOnce(new ApiError(404, ["no project found for lot 'LOT-2024-8841'"]))
      .mockResolvedValueOnce(SUMMARY())
    setup()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      "no project found for lot 'LOT-2024-8841'",
    )
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByText('AD590-JH')
    expect(getLotSummary).toHaveBeenCalledTimes(2)
  })

  test('the two ranked lists are filtered and sorted independently, PASS parts excluded', async () => {
    vi.spyOn(lotDetailApi, 'getLotSummary').mockResolvedValue(SUMMARY())
    setup()
    await screen.findByText('AD590-JH')

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

  test('a ranked-list row links to that component’s Part Detail screen', async () => {
    vi.spyOn(lotDetailApi, 'getLotSummary').mockResolvedValue(SUMMARY())
    setup()
    await screen.findByText('AD590-JH')
    const link = screen.getByRole('link', { name: 'DUT-042' })
    expect(link).toHaveAttribute('href', '/parts/DUT-042')
  })

  test('Generate DPA Work Order only appears for a COMPLETE lot, and renders its recommendations', async () => {
    vi.spyOn(lotDetailApi, 'getLotSummary').mockResolvedValue(SUMMARY())
    const workOrder: MOCK_DPAWorkOrderResponse = {
      recommendations: [
        { component_id: 'DUT-042', reason: 'Highest-severity part in this lot.' },
        { component_id: 'DUT-011', reason: 'Control part from the unflagged population.' },
      ],
    }
    const generateDpaWorkOrder = vi
      .spyOn(lotDetailApi, 'generateDpaWorkOrder')
      .mockResolvedValue(workOrder)
    setup()
    await screen.findByText('AD590-JH')

    const dpaButton = screen.getByRole('button', { name: /generate dpa work order/i })
    fireEvent.click(dpaButton)
    await waitFor(() => expect(generateDpaWorkOrder).toHaveBeenCalledWith('LOT-2024-8841'))
    await screen.findByText('Highest-severity part in this lot.')
  })

  test('Generate DPA Work Order is absent for an In-Progress (forecast) lot', async () => {
    vi.spyOn(lotDetailApi, 'getLotSummary').mockResolvedValue(
      SUMMARY({
        disposition: {
          lot_id: 'LOT-2024-8841',
          status: 'IN_PROGRESS',
          pda_result: 0.01,
          verdict: 'LOT_ON_TRACK',
          is_forecast: true,
        },
      }),
    )
    setup()
    await screen.findByText('AD590-JH')
    expect(screen.queryByRole('button', { name: /generate dpa work order/i })).toBeNull()
    expect(screen.getByText('LOT ON TRACK')).toBeInTheDocument()
    expect(screen.getByText('Forecast')).toBeInTheDocument()
  })

  test('Generate Report downloads the real POST /lots/{lot_id}/report response', async () => {
    vi.spyOn(lotDetailApi, 'getLotSummary').mockResolvedValue(SUMMARY())
    // POST /lots/{lot_id}/report is real (report/router.py, P2); a PDF response, not JSON, so it
    // needs its own Content-Type/Content-Disposition rather than fakeServer's JSON default.
    const realFetch = vi.fn(async (request: Request) => {
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
      await screen.findByText('AD590-JH')

      fireEvent.click(screen.getByRole('button', { name: /generate report/i }))
      await waitFor(() => expect(createObjectURL).toHaveBeenCalled())
      expect(realFetch).toHaveBeenCalledTimes(1)
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
})
