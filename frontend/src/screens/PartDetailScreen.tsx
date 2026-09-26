import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { Data } from 'plotly.js'
import { useId, useState } from 'react'
import RawPlot from 'react-plotly.js'
import { Link, useLocation, useParams } from 'react-router-dom'
import { displayNameFor, TEMP_LOGIN_ACCOUNTS } from '../auth/accounts'
import { useAuth } from '../auth/AuthContext'
import { describeFailure } from '../api/errors'
import { getPartDetail, submitConfirmedOutcome, submitDisposition } from '../api/parts'
import type {
  MOCK_DispositionRecord,
  TEMP_ECODContribution,
  TEMP_FeatureFrame,
  TEMP_MCDContribution,
  TEMP_PartDetailResponse,
} from '../api/mocks'
import { pathToLot } from './registry'
import { VerdictBadge } from './VerdictBadge'

/**
 * Vite's dev-time CJS interop for `react-plotly.js` (it sets both `__esModule` and its own
 * `exports.default`) double-wraps the default export into `{ default: PlotComponent }` rather
 * than unwrapping it once; Rollup's production build doesn't. This falls back to the raw import
 * when there's nothing to unwrap, so it's correct either way (verified against the running dev
 * server, not assumed).
 */
const Plot = (RawPlot as unknown as { default?: typeof RawPlot }).default ?? RawPlot

const CHECKPOINT_ORDER = ['0h', '24h', '96h', '168h'] as const

interface CheckpointRow {
  label: (typeof CHECKPOINT_ORDER)[number]
  hours: number
  measured: number
  median: number
  robustZ: number
  delta: number
}

function checkpointRows(frame: TEMP_FeatureFrame): CheckpointRow[] {
  const values: Record<string, number | null> = {
    '0h': frame.value_0h,
    '24h': frame.value_24h,
    '96h': frame.value_96h,
    '168h': frame.value_168h,
  }
  const deltas: Record<string, number | null> = {
    '0h': 0,
    '24h': frame.delta_24h,
    '96h': frame.delta_96h,
    '168h': frame.delta_168h,
  }
  return CHECKPOINT_ORDER.filter((cp) => values[cp] !== null && values[cp] !== undefined).map(
    (cp) => ({
      label: cp,
      hours: frame.elapsed_hours[cp] ?? Number(cp.replace('h', '')),
      measured: values[cp] as number,
      median: frame.lot_median[cp] ?? 0,
      robustZ: frame.robust_z[cp] ?? 0,
      delta: (deltas[cp] ?? 0) as number,
    }),
  )
}

function formatTimestamp(iso: string): string {
  return iso.slice(0, 16).replace('T', ' ')
}

function NoteCard({
  title,
  text,
  tone = 'info',
}: {
  title: string
  text: string
  tone?: 'info' | 'stale'
}) {
  return (
    <section className={`card note-card note-card-${tone}`} role="note">
      <p className="note-card-title">{title}</p>
      <p className="note-card-text">{text}</p>
    </section>
  )
}

function TrajectoryChart({
  data,
  componentId,
}: {
  data: TEMP_PartDetailResponse
  componentId: string
}) {
  const rows = checkpointRows(data.feature_frame)
  const forecastHours = data.feature_frame.elapsed_hours['168h'] ?? 168
  const traces: Partial<Data>[] = [
    {
      type: 'scatter',
      mode: 'text+lines+markers',
      name: `${componentId} Measured`,
      x: rows.map((r) => r.hours),
      y: rows.map((r) => r.measured),
      text: rows.map((r) => `${r.measured} ${data.feature_frame.unit}`),
      textposition: 'top center',
      line: { color: '#0f172a', width: 2 },
      marker: { color: '#0f172a', size: 6 },
    },
    {
      type: 'scatter',
      mode: 'lines',
      name: 'Lot Median',
      x: rows.map((r) => r.hours),
      y: rows.map((r) => r.median),
      line: { color: '#94a3b8', width: 1.5, dash: 'dot' },
    },
  ]
  if (!data.module_b.forecast_unavailable && data.module_b.predicted_168h !== null) {
    traces.push({
      type: 'scatter',
      mode: 'text+markers',
      name: 'Module B Forecast',
      x: [forecastHours],
      y: [data.module_b.predicted_168h],
      text: [`Module B: ${data.module_b.predicted_168h} ${data.feature_frame.unit}`],
      textposition: 'top right',
      marker: { color: '#b45309', size: 10, symbol: 'square' },
    })
  }

  return (
    <Plot
      data={traces}
      layout={{
        autosize: true,
        margin: { l: 56, r: 24, t: 16, b: 40 },
        height: 340,
        showlegend: true,
        legend: { orientation: 'h', y: 1.15 },
        xaxis: {
          title: { text: '' },
          tickvals: CHECKPOINT_ORDER.map((cp) => data.feature_frame.elapsed_hours[cp]).filter(
            (v): v is number => v !== undefined,
          ),
          ticktext: [...CHECKPOINT_ORDER],
        },
        yaxis: { title: { text: `${data.feature_frame.parameter} (${data.feature_frame.unit})` } },
        font: { family: 'Inter, system-ui, sans-serif', size: 12, color: '#334155' },
      }}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%' }}
      useResizeHandler
    />
  )
}

function DriftMatrix({ frame }: { frame: TEMP_FeatureFrame }) {
  const rows = checkpointRows(frame)
  return (
    <section className="card drift-matrix" aria-label="Checkpoint statistical drift matrix">
      <header className="card-header">
        <h2 className="card-title">Checkpoint Statistical Drift Matrix</h2>
        <span className="card-aside">METHOD: ROBUST MEDIAN ABSOLUTE DEVIATION (MAD)</span>
      </header>
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Checkpoint</th>
            <th scope="col" className="numeric">
              Measured Value
            </th>
            <th scope="col" className="numeric">
              Lot Median
            </th>
            <th scope="col" className="numeric">
              Robust Z-Score
            </th>
            <th scope="col" className="numeric">
              Delta (vs Median)
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className={Math.abs(row.robustZ) >= 3 ? 'row-elevated' : ''}>
              <td className="mono">{row.label}</td>
              <td className="mono numeric">
                {row.measured} {frame.unit}
              </td>
              <td className="mono numeric muted">
                {row.median} {frame.unit}
              </td>
              <td className="mono numeric">
                {row.robustZ >= 0 ? '+' : ''}
                {row.robustZ.toFixed(2)} σ
              </td>
              <td className="mono numeric">
                {row.delta >= 0 ? '+' : ''}
                {row.delta.toFixed(1)} {frame.unit}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function ContributionBar({
  label,
  sublabel,
  valueText,
  pct,
}: {
  label: string
  sublabel?: string
  valueText: string
  pct: number
}) {
  return (
    <div className="contribution-row">
      <div className="contribution-row-head">
        <span>
          {label}
          {sublabel && <span className="muted"> - {sublabel}</span>}
        </span>
        <span className="mono">{valueText}</span>
      </div>
      <div className="contribution-track">
        <div
          className="contribution-fill"
          style={{ width: `${Math.max(2, Math.min(100, pct))}%` }}
        />
      </div>
    </div>
  )
}

function McdCard({ dSquared, rows }: { dSquared: number; rows: TEMP_MCDContribution[] }) {
  return (
    <section className="card contribution-card" aria-label="MCD parameter contribution">
      <header className="card-header">
        <div>
          <h2 className="card-title">MCD Parameter Contribution</h2>
          <p className="card-subtitle">
            Minimum Covariance Determinant (Mahalanobis distance share)
          </p>
        </div>
        <span className="chip mono">D² = {dSquared}</span>
      </header>
      <div className="contribution-list">
        {rows.map((row) => (
          <ContributionBar
            key={row.parameter}
            label={row.parameter}
            valueText={`${row.share_pct}%`}
            pct={row.share_pct}
          />
        ))}
      </div>
    </section>
  )
}

function EcodCard({ oScore, rows }: { oScore: number; rows: TEMP_ECODContribution[] }) {
  const max = Math.max(...rows.map((r) => r.neg_log_p), 0.01)
  return (
    <section className="card contribution-card" aria-label="ECOD tail probability contribution">
      <header className="card-header">
        <div>
          <h2 className="card-title">ECOD Tail Probability Contribution</h2>
          <p className="card-subtitle">Empirical Cumulative Distribution Outlier Detection</p>
        </div>
        <span className="chip mono">O_score = {oScore}</span>
      </header>
      <div className="contribution-list">
        {rows.map((row) => (
          <ContributionBar
            key={row.parameter}
            label={row.parameter}
            sublabel={row.tail}
            valueText={`-log(p) = ${row.neg_log_p}`}
            pct={(row.neg_log_p / max) * 100}
          />
        ))}
      </div>
    </section>
  )
}

function lastSignoff(history: MOCK_DispositionRecord[]): MOCK_DispositionRecord | null {
  if (history.length === 0) return null
  return [...history].sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1))[0]
}

/** E6 screen 4, opened from either ranked list on the Lot Dashboard. */
export function PartDetailScreen() {
  const { componentId } = useParams()
  const location = useLocation()
  const navState = location.state as {
    lotId?: string
    verdict?: 'PASS' | 'WATCH' | 'REJECT'
    worstParameter?: string
  } | null
  const { session } = useAuth()
  const queryClient = useQueryClient()
  const accountId = session?.accountId ?? ''

  const [rationale, setRationale] = useState('')
  const [showConfirmedOutcome, setShowConfirmedOutcome] = useState(false)
  const [confirmedOutcome, setConfirmedOutcome] = useState<
    'Confirmed Good' | 'Confirmed Defective' | 'Unknown'
  >('Confirmed Good')
  const [confirmedNote, setConfirmedNote] = useState('')

  const detail = useQuery({
    queryKey: ['part-detail', componentId],
    queryFn: () =>
      getPartDetail(componentId!, {
        lotId: navState?.lotId,
        verdict: navState?.verdict,
        worstParameter: navState?.worstParameter,
      }),
    enabled: !!componentId,
  })

  const queryKey = ['part-detail', componentId]

  const disposition = useMutation({
    mutationFn: (verdict: 'ACCEPT' | 'HOLD' | 'REJECT') =>
      submitDisposition(componentId!, { verdict, rationale: rationale.trim() }, accountId),
    onSuccess: () => {
      setRationale('')
      void queryClient.invalidateQueries({ queryKey })
    },
  })

  const confirmedOutcomeMutation = useMutation({
    mutationFn: () =>
      submitConfirmedOutcome(
        componentId!,
        { confirmed_outcome: confirmedOutcome, note: confirmedNote.trim() || null },
        accountId,
      ),
    onSuccess: () => {
      setConfirmedNote('')
      setShowConfirmedOutcome(false)
      void queryClient.invalidateQueries({ queryKey })
    },
  })

  const rationaleId = useId()
  const outcomeId = useId()
  const noteId = useId()

  if (!componentId) {
    return (
      <section className="screen">
        <h1 className="screen-title">Part Detail</h1>
        <p className="card-note">No component selected.</p>
      </section>
    )
  }

  if (detail.isPending) {
    return (
      <section className="screen part-detail">
        {/* Not shown; lets a test confirm a URL-encoded component id decoded correctly (P1.9 precedent). */}
        <code data-testid="route-id" className="visually-hidden">
          {componentId}
        </code>
        <h1 className="screen-title">Part Detail</h1>
        <p className="card-note">Loading part detail…</p>
      </section>
    )
  }

  if (detail.isError) {
    return (
      <section className="screen part-detail">
        <code data-testid="route-id" className="visually-hidden">
          {componentId}
        </code>
        <h1 className="screen-title">Part Detail</h1>
        <div className="card-note form-error" role="alert">
          <p>Could not load this part.</p>
          <ul className="message-list">
            {describeFailure(detail.error).map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => detail.refetch()}
          >
            Retry
          </button>
        </div>
      </section>
    )
  }

  const data = detail.data
  const signoff = lastSignoff(data.disposition_history)
  const signoffAccount = TEMP_LOGIN_ACCOUNTS.find((a) => a.account_id === signoff?.account_id)
  const disabledForm = disposition.isPending || rationale.trim() === ''

  return (
    <section className="screen part-detail">
      <code data-testid="route-id" className="visually-hidden">
        {componentId}
      </code>
      <header className="part-detail-header">
        <div className="part-detail-heading">
          <span className="chip">
            DUT IDENTIFIER <span className="mono">{componentId}</span>
          </span>
          <div>
            <p className="summary-label">Primary Target Parameter</p>
            <h1 className="screen-title">{data.module_a.parameter}</h1>
          </div>
        </div>
        <VerdictBadge verdict={data.verdict} />
      </header>
      <p className="part-detail-lot">
        LOT:{' '}
        <Link to={pathToLot(data.lot_id)} className="mono">
          {data.lot_id}
        </Link>
      </p>

      {data.severity_cap_note && (
        <NoteCard title="Explainability Gate Severity-Cap Applied" text={data.severity_cap_note} />
      )}
      {data.staleness_note && (
        <NoteCard title="Analysis Run Stale Notice" text={data.staleness_note} tone="stale" />
      )}
      {data.unavailable_forecast_note && (
        <NoteCard title="Drift Prediction Unavailable" text={data.unavailable_forecast_note} />
      )}

      <div className="part-detail-grid">
        <section className="card trajectory-card" aria-label="Burn-in parameter trajectory">
          <header className="card-header">
            <div>
              <h2 className="card-title">
                Burn-In Parameter Trajectory (0h → 168h Measured
                {data.module_b.forecast_unavailable ? '' : ' & Module B Forecast'})
              </h2>
              <p className="card-subtitle">
                Parameter: {data.module_a.parameter} ({data.feature_frame.unit}) relative to median
                lot baseline
              </p>
            </div>
          </header>
          <TrajectoryChart data={data} componentId={componentId} />
        </section>

        <div className="part-detail-side">
          <section className="card diagnostic-card" aria-label="Diagnostic explanation">
            <header className="card-header">
              <h2 className="card-title">Diagnostic Explanation</h2>
              <span className="chip confidence-chip">{data.confidence_qualifier}</span>
            </header>
            <p className="diagnostic-text">{data.explanation_sentence}</p>
          </section>

          {!data.module_b.forecast_unavailable && (
            <section className="card disagreement-card" aria-label="Model vs physics disagreement">
              <header className="card-header">
                <h2 className="card-title">Model vs. Physics Disagreement</h2>
                <span
                  className={`disagreement-pct ${data.module_b.exceeds_safety_slope ? 'is-reject' : ''}`}
                >
                  {data.module_b.physics_disagreement_gap !== null &&
                  data.module_b.physics_baseline_prediction
                    ? `${data.module_b.physics_disagreement_gap >= 0 ? '+' : ''}${(
                        (data.module_b.physics_disagreement_gap /
                          data.module_b.physics_baseline_prediction) *
                        100
                      ).toFixed(1)}% DISPARITY`
                    : '—'}
                </span>
              </header>
              <div className="disagreement-grid">
                <div>
                  <p className="summary-label">Physics Baseline</p>
                  <p className="mono disagreement-value">
                    {data.module_b.physics_baseline_prediction} {data.feature_frame.unit}
                  </p>
                  <p className="muted">Power-law extrapolation baseline</p>
                </div>
                <div>
                  <p className="summary-label">Live ML Model</p>
                  <p className="mono disagreement-value">
                    {data.module_b.predicted_168h} {data.feature_frame.unit}
                  </p>
                  <p className="muted">Gradient-boosted regression</p>
                </div>
              </div>
              <div className="disagreement-net">
                <p className="summary-label">Net Disagreement Gap</p>
                <p className="mono">
                  {data.module_b.physics_disagreement_gap !== null &&
                  data.module_b.physics_disagreement_gap >= 0
                    ? '+'
                    : ''}
                  {data.module_b.physics_disagreement_gap} {data.feature_frame.unit}
                </p>
              </div>
            </section>
          )}
        </div>
      </div>

      <DriftMatrix frame={data.feature_frame} />

      <div className="contribution-grid">
        <McdCard dSquared={data.mcd_d_squared} rows={data.mcd_contributions} />
        <EcodCard oScore={data.ecod_o_score} rows={data.ecod_contributions} />
      </div>

      <section className="card disposition-card" aria-label="Disposition">
        <header className="disposition-header">
          <div>
            <h2 className="card-title">{data.module_a.parameter}</h2>
            <p className="card-subtitle">
              Record reviewer Accept / Hold for Retest / Reject decision and technical disposition
              rationale.
            </p>
          </div>
          {signoff && (
            <p className="past-signoff">
              Past Sign-off: <VerdictBadge verdict={signoff.verdict} /> by{' '}
              {signoffAccount ? displayNameFor(signoff.account_id) : signoff.account_id} (
              {signoffAccount?.role ?? 'unknown role'}) on {formatTimestamp(signoff.timestamp)}
            </p>
          )}
        </header>

        {disposition.isError && (
          <div className="card-note form-error" role="alert">
            <ul className="message-list">
              {describeFailure(disposition.error).map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          </div>
        )}

        <label className="field-label" htmlFor={rationaleId}>
          Technical Disposition Rationale
        </label>
        <textarea
          id={rationaleId}
          className="input disposition-textarea"
          placeholder="Enter technical rationale for disposition sign-off…"
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          disabled={disposition.isPending}
        />

        <div className="disposition-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => disposition.mutate('ACCEPT')}
            disabled={disabledForm}
          >
            Accept
          </button>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => disposition.mutate('HOLD')}
            disabled={disabledForm}
          >
            Hold for Retest
          </button>
          <button
            type="button"
            className="button button-primary button-reject"
            onClick={() => disposition.mutate('REJECT')}
            disabled={disabledForm}
          >
            Reject
          </button>
          <button
            type="button"
            className="button button-primary record-outcome-toggle"
            onClick={() => setShowConfirmedOutcome((v) => !v)}
          >
            Record Confirmed Outcome
          </button>
        </div>

        {showConfirmedOutcome && (
          <div className="confirmed-outcome-form">
            <div className="confirmed-outcome-row">
              <label className="field-label" htmlFor={outcomeId}>
                Confirmed Outcome
              </label>
              <select
                id={outcomeId}
                className="input"
                value={confirmedOutcome}
                onChange={(e) => setConfirmedOutcome(e.target.value as typeof confirmedOutcome)}
              >
                <option>Confirmed Good</option>
                <option>Confirmed Defective</option>
                <option>Unknown</option>
              </select>
            </div>
            <div className="confirmed-outcome-row">
              <label className="field-label" htmlFor={noteId}>
                Note (optional)
              </label>
              <input
                id={noteId}
                className="input"
                value={confirmedNote}
                onChange={(e) => setConfirmedNote(e.target.value)}
              />
            </div>
            {confirmedOutcomeMutation.isError && (
              <p className="field-error" role="alert">
                {describeFailure(confirmedOutcomeMutation.error).join(' ')}
              </p>
            )}
            <button
              type="button"
              className="button button-secondary"
              onClick={() => confirmedOutcomeMutation.mutate()}
              disabled={confirmedOutcomeMutation.isPending}
            >
              {confirmedOutcomeMutation.isPending ? 'Recording…' : 'Confirm'}
            </button>
          </div>
        )}

        {data.confirmed_outcomes.length > 0 && (
          <ul className="confirmed-outcome-list">
            {data.confirmed_outcomes.map((outcome, i) => (
              <li key={i}>
                {outcome.confirmed_outcome} — recorded by {displayNameFor(outcome.account_id)} on{' '}
                {formatTimestamp(outcome.recorded_at)}
                {outcome.note && `: ${outcome.note}`}
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  )
}
