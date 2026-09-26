import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Link, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { ApiError } from '../api/errors'
import type { TEMP_PartDetailResponse } from '../api/mocks'
import * as partsApi from '../api/parts'
import { fakeServer, renderWithApi } from '../test-utils'
import { PartDetailScreen } from './PartDetailScreen'

// jsdom can't run Plotly's canvas rendering; these tests are about data wiring, not the chart
// library's internals, so the trace/layout props it was given are all that's checked here.
vi.mock('react-plotly.js', () => ({
  default: (props: { data: unknown[] }) => (
    <div data-testid="plotly-stub" data-trace-count={props.data.length} />
  ),
}))

const DETAIL = (overrides: Partial<TEMP_PartDetailResponse> = {}): TEMP_PartDetailResponse => ({
  component_id: 'DUT-042',
  lot_id: 'LOT-2024-W19-B',
  part_number: 'AD590-JH',
  verdict: 'REJECT',
  module_a: {
    component_id: 'DUT-042',
    parameter: 'Leakage Current',
    robust_z: 4.2,
    mcd_distance: 28.4,
    isolation_forest_score: 0.8,
    ecod_score: 0.942,
    explainable_tags: { robust_z: true, mcd: true, isolation_forest: false, ecod: true },
    direction: 'above_median',
    severity_tier: 'REJECT',
    severity_cap_reason: null,
  },
  module_b: {
    component_id: 'DUT-042',
    parameter: 'Leakage Current',
    predicted_168h: 61.5,
    interval_lower: 58,
    interval_upper: 65,
    physics_baseline_prediction: 32.4,
    physics_disagreement_gap: 12.4,
    drift_rate: 0.5,
    exceeds_safety_slope: true,
    safety_slope: 0.3,
    forecast_unavailable: false,
  },
  explanation_sentence:
    'Part DUT-042: leakage at 24h is 4.2 robust-σ above lot median (median = 10 µA, value = 45 µA).',
  confidence_qualifier: 'High confidence',
  severity_cap_note: null,
  unavailable_forecast_note: null,
  staleness_note: null,
  disposition_history: [],
  confirmed_outcomes: [],
  feature_frame: {
    component_id: 'DUT-042',
    lot_id: 'LOT-2024-W19-B',
    part_number: 'AD590-JH',
    parameter: 'Leakage Current',
    unit: 'µA',
    value_0h: 12,
    value_24h: 45,
    value_96h: 52.8,
    value_168h: 60.8,
    delta_24h: 33,
    delta_96h: 40.8,
    delta_168h: 48.8,
    lot_median: { '0h': 10.2, '24h': 10, '96h': 11.1, '168h': 12.4 },
    robust_z: { '0h': 0.68, '24h': 4.2, '96h': 4.86, '168h': 5.08 },
    lot_size: 77,
    used_pooled_fallback: false,
    elapsed_hours: { '0h': 0, '24h': 24, '96h': 96, '168h': 168 },
  },
  mcd_d_squared: 28.4,
  mcd_contributions: [
    { parameter: 'Leakage Current (Iddq)', share_pct: 64.2 },
    { parameter: 'Propagation Delay (tpd)', share_pct: 21.5 },
  ],
  ecod_o_score: 0.942,
  ecod_contributions: [
    { parameter: 'Leakage Current (Iddq)', tail: 'Right Tail', neg_log_p: 4.81 },
    { parameter: 'Propagation Delay (tpd)', tail: 'Right Tail', neg_log_p: 1.34 },
  ],
  ...overrides,
})

const routed = () => (
  <Routes>
    <Route path="/parts/:componentId" element={<PartDetailScreen />} />
  </Routes>
)

function setup(path = '/parts/DUT-042') {
  const server = fakeServer({})
  return renderWithApi(routed(), { fetch: server.fetch, path })
}

/** Jumps between two parts without unmounting anything outside the `<Routes>`, the same way
 * clicking a different ranked-list row does - `routed()` alone can't exercise this. */
const routedWithNav = (other: string) => (
  <>
    {routed()}
    <Link to={other}>go</Link>
  </>
)

describe('Part Detail screen (E6 screen 4)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  test('shows a loading state, then the part detail once the fetch resolves', async () => {
    vi.spyOn(partsApi, 'getPartDetail').mockResolvedValue(DETAIL())
    setup()
    expect(screen.getByText('Loading part detail…')).toBeInTheDocument()
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Leakage Current' }),
    ).toBeInTheDocument()
    expect(screen.getAllByText('DUT-042').length).toBeGreaterThan(0)
    expect(screen.getByText('REJECT')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'LOT-2024-W19-B' })).toHaveAttribute(
      'href',
      '/lots/LOT-2024-W19-B',
    )
  })

  test('a failed fetch shows a retry button, which retries', async () => {
    const getPartDetail = vi
      .spyOn(partsApi, 'getPartDetail')
      .mockRejectedValueOnce(new ApiError(404, ['no such component']))
      .mockResolvedValueOnce(DETAIL())
    setup()
    expect(await screen.findByRole('alert')).toHaveTextContent('no such component')
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    expect(getPartDetail).toHaveBeenCalledTimes(2)
  })

  test('the diagnostic explanation and confidence qualifier are shown verbatim', async () => {
    vi.spyOn(partsApi, 'getPartDetail').mockResolvedValue(DETAIL())
    setup()
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    expect(screen.getByText(DETAIL().explanation_sentence)).toBeInTheDocument()
    expect(screen.getByText('High confidence')).toBeInTheDocument()
  })

  test('the checkpoint drift matrix has one row per present checkpoint, in order', async () => {
    vi.spyOn(partsApi, 'getPartDetail').mockResolvedValue(DETAIL())
    setup()
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    const table = screen.getByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((r) => within(r).getAllByRole('cell')[0].textContent)).toEqual([
      '0h',
      '24h',
      '96h',
      '168h',
    ])
    expect(within(rows[1]).getAllByRole('cell')[1]).toHaveTextContent('45 µA')
    expect(within(rows[1]).getAllByRole('cell')[3]).toHaveTextContent('+4.20 σ')
  })

  test('a checkpoint with no reading yet (In-Progress lot) is left out of the matrix, not shown as zero', async () => {
    vi.spyOn(partsApi, 'getPartDetail').mockResolvedValue(
      DETAIL({
        feature_frame: {
          ...DETAIL().feature_frame,
          value_96h: null,
          value_168h: null,
          delta_96h: null,
          delta_168h: null,
        },
      }),
    )
    setup()
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    const table = screen.getByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((r) => within(r).getAllByRole('cell')[0].textContent)).toEqual(['0h', '24h'])
  })

  test('MCD and ECOD contribution charts render their rows and summary badges', async () => {
    vi.spyOn(partsApi, 'getPartDetail').mockResolvedValue(DETAIL())
    setup()
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    expect(screen.getByText('D² = 28.4')).toBeInTheDocument()
    expect(screen.getByText('O_score = 0.942')).toBeInTheDocument()
    expect(screen.getByText('64.2%')).toBeInTheDocument()
    expect(screen.getByText('-log(p) = 4.81')).toBeInTheDocument()
  })

  test('the severity-cap, staleness and unavailable-forecast notes only appear when present', async () => {
    vi.spyOn(partsApi, 'getPartDetail').mockResolvedValue(DETAIL())
    setup()
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    expect(screen.queryByText('Explainability Gate Severity-Cap Applied')).toBeNull()
    expect(screen.queryByText('Analysis Run Stale Notice')).toBeNull()
    expect(screen.queryByText('Drift Prediction Unavailable')).toBeNull()
  })

  test('a capped severity, a stale run and an unavailable forecast each show their own note', async () => {
    vi.spyOn(partsApi, 'getPartDetail').mockResolvedValue(
      DETAIL({
        severity_cap_note: 'Module A raw score flagged REJECT ... capped at WATCH.',
        staleness_note:
          'Newer analysis run #03 exists compared to disposition sign-off baseline #02.',
        unavailable_forecast_note: 'Supply Slew Drift falls outside the three trained parameters.',
        module_b: { ...DETAIL().module_b, forecast_unavailable: true, predicted_168h: null },
      }),
    )
    setup()
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    expect(screen.getByText('Explainability Gate Severity-Cap Applied')).toBeInTheDocument()
    expect(screen.getByText('Analysis Run Stale Notice')).toBeInTheDocument()
    expect(screen.getByText('Drift Prediction Unavailable')).toBeInTheDocument()
    expect(screen.queryByText('Model vs. Physics Disagreement')).toBeNull()
  })

  test('a past sign-off is shown, with the deciding account and role', async () => {
    vi.spyOn(partsApi, 'getPartDetail').mockResolvedValue(
      DETAIL({
        disposition_history: [
          {
            project_id: 'proj-1',
            component_id: 'DUT-042',
            account_id: 'a.sharma',
            verdict: 'REJECT',
            rationale: 'Leakage well past REVIEW at 24h.',
            timestamp: '2024-05-12T15:40:00',
            analysis_run_id: '02',
          },
        ],
      }),
    )
    setup()
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    const note = screen.getByText(/Past Sign-off:/)
    expect(note).toHaveTextContent('A. Sharma')
    expect(note).toHaveTextContent('Quality Engineer')
    expect(note).toHaveTextContent('2024-05-12 15:40')
  })

  test('disposition buttons stay disabled until a rationale is entered, then submit it', async () => {
    vi.spyOn(partsApi, 'getPartDetail').mockResolvedValue(DETAIL())
    const submitDisposition = vi.spyOn(partsApi, 'submitDisposition').mockResolvedValue({
      project_id: 'proj-1',
      component_id: 'DUT-042',
      account_id: 'a.sharma',
      verdict: 'REJECT',
      rationale: 'Confirmed leakage drift.',
      timestamp: '2026-09-26T10:00:00',
      analysis_run_id: '03',
    })
    setup()
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })

    const reject = screen.getByRole('button', { name: 'Reject' })
    expect(reject).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Technical Disposition Rationale'), {
      target: { value: 'Confirmed leakage drift.' },
    })
    expect(reject).toBeEnabled()

    fireEvent.click(reject)
    await waitFor(() =>
      expect(submitDisposition).toHaveBeenCalledWith(
        'DUT-042',
        { verdict: 'REJECT', rationale: 'Confirmed leakage drift.' },
        'a.sharma',
      ),
    )
    await waitFor(() =>
      expect(screen.getByLabelText('Technical Disposition Rationale')).toHaveValue(''),
    )
  })

  test('a failed disposition submission shows the server message', async () => {
    vi.spyOn(partsApi, 'getPartDetail').mockResolvedValue(DETAIL())
    vi.spyOn(partsApi, 'submitDisposition').mockRejectedValue(
      new ApiError(422, ['A technical rationale is required.']),
    )
    setup()
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    fireEvent.change(screen.getByLabelText('Technical Disposition Rationale'), {
      target: { value: 'x' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('A technical rationale is required.')
  })

  test('Record Confirmed Outcome reveals its own form, separate from the disposition action', async () => {
    vi.spyOn(partsApi, 'getPartDetail').mockResolvedValue(DETAIL())
    const submitConfirmedOutcome = vi.spyOn(partsApi, 'submitConfirmedOutcome').mockResolvedValue({
      project_id: 'proj-1',
      component_id: 'DUT-042',
      account_id: 'a.sharma',
      confirmed_outcome: 'Confirmed Defective',
      note: null,
      recorded_at: '2026-09-26T10:00:00',
      analysis_run_id: '03',
    })
    setup()
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })

    expect(screen.queryByLabelText('Confirmed Outcome')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Record Confirmed Outcome' }))
    fireEvent.change(screen.getByLabelText('Confirmed Outcome'), {
      target: { value: 'Confirmed Defective' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() =>
      expect(submitConfirmedOutcome).toHaveBeenCalledWith(
        'DUT-042',
        { confirmed_outcome: 'Confirmed Defective', note: null },
        'a.sharma',
      ),
    )
  })

  test('no component selected shows a note instead of crashing', () => {
    const server = fakeServer({})
    renderWithApi(
      <Routes>
        <Route path="/" element={<PartDetailScreen />} />
      </Routes>,
      { fetch: server.fetch, path: '/' },
    )
    expect(screen.getByText('No component selected.')).toBeInTheDocument()
  })

  test('navigating to a different part clears an unsent rationale, not just its own screen', async () => {
    vi.spyOn(partsApi, 'getPartDetail').mockResolvedValue(DETAIL())
    const server = fakeServer({})
    renderWithApi(routedWithNav('/parts/DUT-008'), { fetch: server.fetch, path: '/parts/DUT-042' })
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })

    fireEvent.change(screen.getByLabelText('Technical Disposition Rationale'), {
      target: { value: 'Half-typed note meant for DUT-042 only.' },
    })

    fireEvent.click(screen.getByRole('link', { name: 'go' }))
    await waitFor(() => expect(screen.getByTestId('route-id')).toHaveTextContent('DUT-008'))
    await screen.findByLabelText('Technical Disposition Rationale')
    expect(screen.getByLabelText('Technical Disposition Rationale')).toHaveValue('')
    // And the buttons are disabled again, since the new screen starts with no rationale either.
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
  })

  test('navigating to a different part clears a stale disposition error from the previous one', async () => {
    vi.spyOn(partsApi, 'getPartDetail').mockResolvedValue(DETAIL())
    vi.spyOn(partsApi, 'submitDisposition').mockRejectedValue(
      new ApiError(422, ['A technical rationale is required.']),
    )
    const server = fakeServer({})
    renderWithApi(routedWithNav('/parts/DUT-008'), { fetch: server.fetch, path: '/parts/DUT-042' })
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })

    fireEvent.change(screen.getByLabelText('Technical Disposition Rationale'), {
      target: { value: 'x' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('A technical rationale is required.')

    fireEvent.click(screen.getByRole('link', { name: 'go' }))
    await waitFor(() => expect(screen.getByTestId('route-id')).toHaveTextContent('DUT-008'))
    expect(screen.queryByRole('alert')).toBeNull()
  })

  test('navigating to a different part collapses an open Record Confirmed Outcome form', async () => {
    vi.spyOn(partsApi, 'getPartDetail').mockResolvedValue(DETAIL())
    const server = fakeServer({})
    renderWithApi(routedWithNav('/parts/DUT-008'), { fetch: server.fetch, path: '/parts/DUT-042' })
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })

    fireEvent.click(screen.getByRole('button', { name: 'Record Confirmed Outcome' }))
    expect(screen.getByLabelText('Confirmed Outcome')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('link', { name: 'go' }))
    await waitFor(() => expect(screen.getByTestId('route-id')).toHaveTextContent('DUT-008'))
    expect(screen.queryByLabelText('Confirmed Outcome')).toBeNull()
  })
})
