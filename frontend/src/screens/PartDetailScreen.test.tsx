import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Link, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import * as partsApi from '../api/parts'
import type { PartDetailResponse } from '../api/parts'
import { fakeServer, renderWithApi } from '../test-utils'
import { PartDetailScreen } from './PartDetailScreen'

// jsdom can't run Plotly's canvas rendering; these tests are about data wiring, not the chart
// library's internals, so the trace/layout props it was given are all that's checked here.
vi.mock('react-plotly.js', () => ({
  default: (props: { data: unknown[] }) => (
    <div data-testid="plotly-stub" data-trace-count={props.data.length} />
  ),
}))

const MODULE_A: NonNullable<PartDetailResponse['module_a']> = {
  component_id: 'DUT-042',
  lot_id: 'LOT-2024-W19-B',
  parameter: 'Leakage Current',
  robust_z: 4.2,
  mcd_distance: 28.4,
  isolation_forest_score: 0.8,
  ecod_score: 0.942,
  explainable_tags: { robust_z: true, mcd: true, isolation_forest: false, ecod: true },
  direction: 'above_median',
  severity_tier: 'REJECT',
  severity_cap_reason: null,
  combined_severity: 0.91,
  explainable_corroboration: true,
}

const MODULE_B: NonNullable<PartDetailResponse['module_b']> = {
  component_id: 'DUT-042',
  lot_id: 'LOT-2024-W19-B',
  parameter: 'Leakage Current',
  predicted_168h: 61.5,
  interval_lower: 58,
  interval_upper: 65,
  physics_baseline_prediction: 32.4,
  physics_disagreement_gap: 12.4,
  drift_rate: 0.5,
  exceeds_safety_slope: true,
  lower_bound_exceeds_safety_slope: true,
  safety_slope: 0.3,
  forecast_unavailable: false,
}

const EXPLANATION: NonNullable<PartDetailResponse['explanation']> = {
  zscore_table: [{ parameter: 'Leakage Current', value: 45, lot_median: 10, z: 4.2 }],
  mcd_contributions: [
    { parameter: 'Leakage Current', contribution: 18.2 },
    { parameter: 'Propagation Delay', contribution: 6.1 },
  ],
  ecod_dimensions: [
    { dimension: 'Leakage Current', score: 4.81 },
    { dimension: 'Propagation Delay', score: 1.34 },
  ],
  shap_contributions: [{ feature: 'delta_24h', value: 33, shap_value: 0.62 }],
  explanation_sentence: null,
  confidence_qualifier: null,
  severity_cap_note: null,
  unavailable_forecast_note: null,
  trajectory: [
    { checkpoint_hour: 0, value: 9.8, lot_median: 9.5 },
    { checkpoint_hour: 24, value: 45, lot_median: 10 },
  ],
}

const DETAIL = (overrides: Partial<PartDetailResponse> = {}): PartDetailResponse => ({
  module_a: MODULE_A,
  module_b: MODULE_B,
  explanation_sentence:
    'Part DUT-042: leakage at 24h is 4.2 robust-σ above lot median (median = 10, value = 45).',
  confidence_qualifier: 'High confidence',
  severity_cap_note: null,
  unavailable_forecast_note: null,
  staleness_note: null,
  disposition_history: [],
  confirmed_outcomes: [],
  explanation: EXPLANATION,
  component_id: 'DUT-042',
  lot_id: 'LOT-2024-W19-B',
  project_id: 'proj-LOT-2024-W19-B',
  analysis_run_id: '03',
  verdict: 'REJECT',
  ...overrides,
})

const routed = () => (
  <Routes>
    <Route path="/parts/:componentId" element={<PartDetailScreen />} />
  </Routes>
)

function setup(path = '/parts/DUT-042', detail: PartDetailResponse = DETAIL()) {
  const server = fakeServer({ 'GET /parts/DUT-042': { body: detail } })
  return { ...renderWithApi(routed(), { fetch: server.fetch, path }), ...server }
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

  test('shows a loading state, then a complete part with both modules and all charts', async () => {
    setup()
    expect(screen.getByText('Loading part detail…')).toBeInTheDocument()
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Leakage Current' }),
    ).toBeInTheDocument()
    expect(screen.getAllByText('DUT-042').length).toBeGreaterThan(0)
    expect(screen.getByText('High confidence')).toBeInTheDocument()
    // Z-score table.
    expect(screen.getByText('24h Z-Score Table')).toBeInTheDocument()
    expect(screen.getByText('+4.20 σ')).toBeInTheDocument()
    // MCD / ECOD.
    expect(screen.getByText('D² = 28.4')).toBeInTheDocument()
    expect(screen.getByText('O_score = 0.942')).toBeInTheDocument()
    // SHAP.
    expect(screen.getByText('SHAP Feature Contribution')).toBeInTheDocument()
    expect(screen.getByText('delta_24h')).toBeInTheDocument()
    // Trajectory chart rendered (stubbed), physics-disagreement card shown.
    expect(screen.getByTestId('plotly-stub')).toBeInTheDocument()
    expect(screen.getByText('Model vs. Physics Disagreement')).toBeInTheDocument()
    expect(screen.queryByText(/runs when the lot is Complete/)).toBeNull()
  })

  test('a failed fetch shows a retry button, which retries', async () => {
    let calls = 0
    const server = fakeServer({
      'GET /parts/DUT-042': () =>
        ++calls === 1
          ? { status: 404, body: { detail: 'no such component' } }
          : { body: DETAIL() },
    })
    renderWithApi(routed(), { fetch: server.fetch, path: '/parts/DUT-042' })
    expect(await screen.findByRole('alert')).toHaveTextContent('no such component')
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    expect(calls).toBe(2)
  })

  test('the diagnostic explanation is shown verbatim', async () => {
    setup()
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    expect(screen.getByText(DETAIL().explanation_sentence)).toBeInTheDocument()
  })

  test('an in-progress part: module_a null hides its sections, module_b present, a null SHAP value renders "not available yet" and keeps its bar', async () => {
    setup(
      '/parts/DUT-042',
      DETAIL({
        module_a: null,
        explanation: {
          ...EXPLANATION,
          shap_contributions: [{ feature: 'delta_24h', value: null, shap_value: 0.4 }],
        },
      }),
    )
    // Falls back to module_b.parameter as the heading since module_a is null.
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    expect(screen.getAllByText('Module A runs when the lot is Complete.').length).toBeGreaterThan(
      0,
    )
    expect(screen.queryByText('MCD Parameter Contribution')).toBeNull()
    expect(screen.queryByText('ECOD Dimension Score')).toBeNull()
    // Module B content still renders.
    expect(screen.getByText('Model vs. Physics Disagreement')).toBeInTheDocument()
    expect(screen.getByText(/not available yet/)).toBeInTheDocument()
    const shapCard = screen.getByRole('region', { name: 'SHAP feature contribution' })
    expect(within(shapCard).getByText('+0.400')).toBeInTheDocument()
  })

  test('module_b null hides its sections the same way, with the trajectory chart replaced too', async () => {
    setup('/parts/DUT-042', DETAIL({ module_b: null }))
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    expect(screen.getAllByText('Module B runs when the lot is Complete.').length).toBe(2) // trajectory slot + side panel
    expect(screen.queryByText('Model vs. Physics Disagreement')).toBeNull()
    expect(screen.queryByText('SHAP Feature Contribution')).toBeNull()
    expect(screen.queryByTestId('plotly-stub')).toBeNull()
  })

  test('the checkpoint z-score table has one row per parameter with data', async () => {
    setup(
      '/parts/DUT-042',
      DETAIL({
        explanation: {
          ...EXPLANATION,
          zscore_table: [
            { parameter: 'Leakage Current', value: 45, lot_median: 10, z: 4.2 },
            { parameter: 'Propagation Delay', value: 3.1, lot_median: 2.9, z: 0.4 },
          ],
        },
      }),
    )
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    const table = screen.getByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((r) => within(r).getAllByRole('cell')[0].textContent)).toEqual([
      'Leakage Current',
      'Propagation Delay',
    ])
  })

  test('the severity-cap, unavailable-forecast and staleness notes only appear when present', async () => {
    setup()
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    expect(screen.queryByText('Explainability Gate Severity-Cap Applied')).toBeNull()
    expect(screen.queryByText('Analysis Run Stale Notice')).toBeNull()
    expect(screen.queryByText('Drift Prediction Unavailable')).toBeNull()
  })

  test('a capped severity, a stale run and an unavailable forecast each show their own note, and the note replaces the trajectory chart', async () => {
    setup(
      '/parts/DUT-042',
      DETAIL({
        severity_cap_note: 'Module A raw score flagged REJECT ... capped at WATCH.',
        staleness_note:
          'Newer analysis run #03 exists compared to disposition sign-off baseline #02.',
        unavailable_forecast_note: 'Supply Slew Drift falls outside the three trained parameters.',
        module_b: { ...MODULE_B, forecast_unavailable: true, predicted_168h: null },
      }),
    )
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    expect(screen.getByText('Explainability Gate Severity-Cap Applied')).toBeInTheDocument()
    expect(screen.getByText('Analysis Run Stale Notice')).toBeInTheDocument()
    expect(screen.getAllByText('Supply Slew Drift falls outside the three trained parameters.'))
      .toHaveLength(2) // top note card + in place of the chart
    expect(screen.queryByText('Model vs. Physics Disagreement')).toBeNull()
    expect(screen.queryByTestId('plotly-stub')).toBeNull()
  })

  test('a PASS part with no stored explanation shows the plain sentence and no empty chart frames', async () => {
    setup(
      '/parts/DUT-042',
      DETAIL({
        module_a: { ...MODULE_A, severity_tier: 'PASS' },
        explanation_sentence: 'within normal range',
        confidence_qualifier: '',
        explanation: {
          zscore_table: [],
          mcd_contributions: [],
          ecod_dimensions: [],
          shap_contributions: [],
          explanation_sentence: null,
          confidence_qualifier: null,
          severity_cap_note: null,
          unavailable_forecast_note: null,
          trajectory: [],
        },
      }),
    )
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    expect(screen.getByText('within normal range')).toBeInTheDocument()
    expect(screen.queryByText('24h Z-Score Table')).toBeNull()
    expect(screen.queryByText('MCD Parameter Contribution')).toBeNull()
    expect(screen.queryByText('ECOD Dimension Score')).toBeNull()
    expect(screen.queryByText('SHAP Feature Contribution')).toBeNull()
  })

  const SIGNOFF = (account_id: string, timestamp: string) => ({
    project_id: 'proj-LOT-2024-W19-B',
    component_id: 'DUT-042',
    account_id,
    verdict: 'REJECT' as const,
    rationale: 'Leakage well past REVIEW at 24h.',
    timestamp,
    analysis_run_id: '03',
  })

  test('the header shows the response verdict and component id, not navigation state', async () => {
    setup('/parts/DUT-042', DETAIL({ verdict: 'WATCH', component_id: 'DUT-042' }))
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    const header = document.querySelector('.part-detail-header') as HTMLElement
    expect(within(header).getByText('WATCH')).toBeInTheDocument()
    expect(within(header).getByText('DUT-042')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'LOT-2024-W19-B' })).toBeInTheDocument()
  })

  test('the sign-off history lists every sign-off with account, verdict, time and run, and counts distinct accounts', async () => {
    setup(
      '/parts/DUT-042',
      DETAIL({
        disposition_history: [
          SIGNOFF('a.sharma', '2026-09-30T10:00:00'),
          SIGNOFF('r.mehta', '2026-09-30T10:05:00'),
        ],
      }),
    )
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    const history = screen.getByLabelText('Sign-off history')
    expect(history).toHaveTextContent('2 sign-off(s) recorded by distinct accounts')
    const items = within(history).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('a.sharma')
    expect(items[0]).toHaveTextContent('2026-09-30 10:00:00')
    expect(items[0]).toHaveTextContent('run 03')
    expect(items[1]).toHaveTextContent('r.mehta')
    expect(screen.queryByText(/finalized/i)).toBeNull()
  })

  test('the same account signing twice counts as one distinct account', async () => {
    setup(
      '/parts/DUT-042',
      DETAIL({
        disposition_history: [
          SIGNOFF('a.sharma', '2026-09-30T10:00:00'),
          SIGNOFF('a.sharma', '2026-09-30T10:01:00'),
        ],
      }),
    )
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    expect(screen.getByLabelText('Sign-off history')).toHaveTextContent(
      '1 sign-off(s) recorded by distinct accounts',
    )
  })

  test('a disposition posts to the real route with the ids from the response, enabled without a rationale, then refreshes the part and worklist', async () => {
    let body: unknown = null
    const server = fakeServer({
      'GET /parts/DUT-042': { body: DETAIL() },
      'POST /parts/DUT-042/disposition': async (request) => {
        body = await request.json()
        return { body: SIGNOFF('a.sharma', '2026-09-30T10:00:00') }
      },
    })
    const { queryClient } = renderWithApi(routed(), {
      fetch: server.fetch,
      path: '/parts/DUT-042',
    })
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    const reject = screen.getByRole('button', { name: 'Reject' })
    expect(reject).toBeEnabled()
    fireEvent.change(screen.getByLabelText('Technical Disposition Rationale (optional)'), {
      target: { value: 'Confirmed leakage drift.' },
    })
    fireEvent.click(reject)

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toEqual({ verdict: 'REJECT', rationale: 'Confirmed leakage drift.' })
    const post = server.requests.find((r) => r.method === 'POST') as Request
    const url = new URL(post.url)
    expect(url.searchParams.get('project_id')).toBe('proj-LOT-2024-W19-B')
    expect(url.searchParams.get('analysis_run_id')).toBe('03')
    await waitFor(() =>
      expect(screen.getByLabelText('Technical Disposition Rationale (optional)')).toHaveValue(''),
    )
    expect(invalidate.mock.calls.some((c) => c[0]?.queryKey?.[0] === 'part-detail')).toBe(true)
    expect(invalidate.mock.calls.some((c) => c[0]?.queryKey?.[1] === 'worklist')).toBe(true)
  })

  test('a same-account retry shows the server 400 message', async () => {
    const server = fakeServer({
      'GET /parts/DUT-042': { body: DETAIL() },
      'POST /parts/DUT-042/disposition': {
        status: 400,
        body: { detail: 'Dual sign-off requires two distinct account IDs, not two role labels' },
      },
    })
    renderWithApi(routed(), { fetch: server.fetch, path: '/parts/DUT-042' })
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Dual sign-off requires two distinct account IDs, not two role labels',
    )
  })

  test('a response without project/analysis-run ids disables the disposition buttons', async () => {
    setup('/parts/DUT-042', DETAIL({ project_id: null, analysis_run_id: null }))
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
  })

  test('Record Confirmed Outcome reveals its own form, separate from the disposition action', async () => {
    setup()
    const submitConfirmedOutcome = vi.spyOn(partsApi, 'submitConfirmedOutcome').mockResolvedValue({
      project_id: 'proj-1',
      component_id: 'DUT-042',
      account_id: 'a.sharma',
      confirmed_outcome: 'Confirmed Defective',
      note: null,
      recorded_at: '2026-09-26T10:00:00',
      analysis_run_id: '03',
    })
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })

    expect(screen.queryByLabelText('Confirmed Outcome')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Record Confirmed Outcome' }))
    fireEvent.change(screen.getByLabelText('Confirmed Outcome'), {
      target: { value: 'Confirmed Defective' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() =>
      expect(submitConfirmedOutcome).toHaveBeenCalledWith(
        expect.anything(),
        'DUT-042',
        { confirmed_outcome: 'Confirmed Defective', note: null },
        undefined,
      ),
    )
  })

  test('recording a confirmed outcome refreshes both the part and the worklist', async () => {
    const { queryClient } = setup()
    vi.spyOn(partsApi, 'submitConfirmedOutcome').mockResolvedValue({
      project_id: 'proj-1',
      component_id: 'DUT-042',
      account_id: 'a.sharma',
      confirmed_outcome: 'Confirmed Good',
      note: null,
      recorded_at: '2026-09-26T10:00:00',
      analysis_run_id: '03',
    })
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    fireEvent.click(screen.getByRole('button', { name: 'Record Confirmed Outcome' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() =>
      expect(invalidate.mock.calls.some((c) => c[0]?.queryKey?.[0] === 'part-detail')).toBe(true),
    )
    expect(
      invalidate.mock.calls.some(
        (c) => c[0]?.queryKey?.[0] === 'settings' && c[0]?.queryKey?.[1] === 'worklist',
      ),
    ).toBe(true)
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
    const server = fakeServer({
      'GET /parts/DUT-042': { body: DETAIL() },
      'GET /parts/DUT-008': { body: DETAIL({ module_a: { ...MODULE_A, parameter: 'Iddq' } }) },
    })
    renderWithApi(routedWithNav('/parts/DUT-008'), { fetch: server.fetch, path: '/parts/DUT-042' })
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })

    fireEvent.change(screen.getByLabelText('Technical Disposition Rationale (optional)'), {
      target: { value: 'Half-typed note meant for DUT-042 only.' },
    })

    fireEvent.click(screen.getByRole('link', { name: 'go' }))
    await waitFor(() => expect(screen.getByTestId('route-id')).toHaveTextContent('DUT-008'))
    await screen.findByLabelText('Technical Disposition Rationale (optional)')
    expect(screen.getByLabelText('Technical Disposition Rationale (optional)')).toHaveValue('')
  })

  test('navigating to a different part clears a stale disposition error from the previous one', async () => {
    const server = fakeServer({
      'GET /parts/DUT-042': { body: DETAIL() },
      'GET /parts/DUT-008': { body: DETAIL() },
      'POST /parts/DUT-042/disposition': { status: 400, body: { detail: 'Rejected by server.' } },
    })
    renderWithApi(routedWithNav('/parts/DUT-008'), { fetch: server.fetch, path: '/parts/DUT-042' })
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })

    fireEvent.change(screen.getByLabelText('Technical Disposition Rationale (optional)'), {
      target: { value: 'x' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Rejected by server.')

    fireEvent.click(screen.getByRole('link', { name: 'go' }))
    await waitFor(() => expect(screen.getByTestId('route-id')).toHaveTextContent('DUT-008'))
    expect(screen.queryByRole('alert')).toBeNull()
  })

  test('navigating to a different part collapses an open Record Confirmed Outcome form', async () => {
    const server = fakeServer({
      'GET /parts/DUT-042': { body: DETAIL() },
      'GET /parts/DUT-008': { body: DETAIL() },
    })
    renderWithApi(routedWithNav('/parts/DUT-008'), { fetch: server.fetch, path: '/parts/DUT-042' })
    await screen.findByRole('heading', { level: 1, name: 'Leakage Current' })

    fireEvent.click(screen.getByRole('button', { name: 'Record Confirmed Outcome' }))
    expect(screen.getByLabelText('Confirmed Outcome')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('link', { name: 'go' }))
    await waitFor(() => expect(screen.getByTestId('route-id')).toHaveTextContent('DUT-008'))
    expect(screen.queryByLabelText('Confirmed Outcome')).toBeNull()
  })
})
