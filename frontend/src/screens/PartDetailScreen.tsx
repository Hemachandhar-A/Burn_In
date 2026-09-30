import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { Data } from 'plotly.js'
import { useId, useState } from 'react'
import RawPlot from 'react-plotly.js'
import { Link, useLocation, useParams } from 'react-router-dom'
import { useApiClient } from '../api/ApiClientContext'
import { displayNameFor, TEMP_LOGIN_ACCOUNTS } from '../auth/accounts'
import { useAuth } from '../auth/AuthContext'
import { describeFailure } from '../api/errors'
import { getPartDetail, submitConfirmedOutcome, submitDisposition } from '../api/parts'
import type { PartDetailResponse } from '../api/parts'
import type { components } from '../api/schema'
import { WORKLIST_QUERY_KEY } from '../api/settings'
import { pathToLot } from './registry'
import { VerdictBadge } from './VerdictBadge'

type DispositionRecord = components['schemas']['DispositionRecord']
type ZScoreTableRow = components['schemas']['ZScoreTableRow']
type MCDContributionRow = components['schemas']['MCDContributionRow']
type EcodDimensionRow = components['schemas']['EcodDimensionRow']
type ShapContributionRow = components['schemas']['ShapContributionRow']

/**
 * Vite's dev-time CJS interop for `react-plotly.js` (it sets both `__esModule` and its own
 * `exports.default`) double-wraps the default export into `{ default: PlotComponent }` rather
 * than unwrapping it once; Rollup's production build doesn't. This falls back to the raw import
 * when there's nothing to unwrap, so it's correct either way (verified against the running dev
 * server, not assumed).
 */
const Plot = (RawPlot as unknown as { default?: typeof RawPlot }).default ?? RawPlot

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

/** E6 screen 4's "hide the section, show a neutral line" treatment for a module that didn't run. */
function ModuleUnavailable({ module }: { module: 'A' | 'B' }) {
  return <p className="card-note">Module {module} runs when the lot is Complete.</p>
}

/**
 * The parameter this screen is primarily about: whichever module actually ran names it first
 * (both agree when both ran), falling back to the first parameter the 24h z-score table has for
 * a part where neither module produced a result yet (rare - Module B attempts a result whenever
 * a frame exists, but the type allows it, rule 7).
 */
function primaryParameter(data: PartDetailResponse): string | null {
  return (
    data.module_a?.parameter ??
    data.module_b?.parameter ??
    data.explanation?.zscore_table[0]?.parameter ??
    null
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

/** `mcd_contributions[].contribution` is a raw per-parameter squared-Mahalanobis term (they sum
 * to the part's D²), not a percentage - normalized here for the bar width, a display computation
 * over already-real numbers, not composed explanation text. */
function McdCard({ dSquared, rows }: { dSquared: number | null; rows: MCDContributionRow[] }) {
  if (rows.length === 0) return null
  const total = rows.reduce((sum, r) => sum + Math.max(0, r.contribution), 0)
  return (
    <section className="card contribution-card" aria-label="MCD parameter contribution">
      <header className="card-header">
        <div>
          <h2 className="card-title">MCD Parameter Contribution</h2>
          <p className="card-subtitle">
            Minimum Covariance Determinant (Mahalanobis distance share)
          </p>
        </div>
        <span className="chip mono">D² = {dSquared ?? '—'}</span>
      </header>
      <div className="contribution-list">
        {rows.map((row) => (
          <ContributionBar
            key={row.parameter}
            label={row.parameter}
            valueText={row.contribution.toFixed(2)}
            pct={total > 0 ? (Math.max(0, row.contribution) / total) * 100 : 0}
          />
        ))}
      </div>
    </section>
  )
}

function EcodCard({ oScore, rows }: { oScore: number | null; rows: EcodDimensionRow[] }) {
  if (rows.length === 0) return null
  const max = Math.max(...rows.map((r) => r.score), 0.01)
  return (
    <section className="card contribution-card" aria-label="ECOD dimension score">
      <header className="card-header">
        <div>
          <h2 className="card-title">ECOD Dimension Score</h2>
          <p className="card-subtitle">Empirical Cumulative Distribution Outlier Detection</p>
        </div>
        <span className="chip mono">O_score = {oScore ?? '—'}</span>
      </header>
      <div className="contribution-list">
        {rows.map((row) => (
          <ContributionBar
            key={row.dimension}
            label={row.dimension}
            valueText={`score = ${row.score.toFixed(3)}`}
            pct={(row.score / max) * 100}
          />
        ))}
      </div>
    </section>
  )
}

/** SHAP rows whose `value` is null render "not available yet", never 0 - they still keep their
 * contribution bar (E12/rule 7: a missing feature is not the same as a zero one). */
function ShapCard({ rows }: { rows: ShapContributionRow[] }) {
  if (rows.length === 0) return null
  const max = Math.max(...rows.map((r) => Math.abs(r.shap_value)), 0.01)
  return (
    <section className="card contribution-card" aria-label="SHAP feature contribution">
      <header className="card-header">
        <div>
          <h2 className="card-title">SHAP Feature Contribution</h2>
          <p className="card-subtitle">Module B's drift-prediction model, per feature</p>
        </div>
      </header>
      <div className="contribution-list">
        {rows.map((row) => (
          <ContributionBar
            key={row.feature}
            label={row.feature}
            sublabel={row.value === null ? 'not available yet' : String(row.value)}
            valueText={`${row.shap_value >= 0 ? '+' : ''}${row.shap_value.toFixed(3)}`}
            pct={(Math.abs(row.shap_value) / max) * 100}
          />
        ))}
      </div>
    </section>
  )
}

function ZScoreTable({ rows }: { rows: ZScoreTableRow[] }) {
  if (rows.length === 0) return null
  return (
    <section className="card drift-matrix" aria-label="24h z-score table">
      <header className="card-header">
        <h2 className="card-title">24h Z-Score Table</h2>
        <span className="card-aside">METHOD: ROBUST MEDIAN ABSOLUTE DEVIATION (MAD)</span>
      </header>
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Parameter</th>
            <th scope="col" className="numeric">
              Value (24h)
            </th>
            <th scope="col" className="numeric">
              Lot Median (24h)
            </th>
            <th scope="col" className="numeric">
              Robust Z-Score
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.parameter} className={Math.abs(row.z) >= 3 ? 'row-elevated' : ''}>
              <td>{row.parameter}</td>
              <td className="mono numeric">{row.value}</td>
              <td className="mono numeric muted">{row.lot_median}</td>
              <td className="mono numeric">
                {row.z >= 0 ? '+' : ''}
                {row.z.toFixed(2)} σ
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

/**
 * The trajectory chart's only real data points, per CONTRACT_CHANGES.md ("PartDetailResponse
 * gives the frontend no way to..." entry family, item 4 status update): a 24h measured point
 * (from the z-score table, matched to `parameter`) and Module B's 168h forecast + interval - no
 * 0h value reaches the frontend in the current response.
 */
function TrajectoryChart({
  data,
  parameter,
}: {
  data: PartDetailResponse
  parameter: string
}) {
  const zscoreRow = data.explanation?.zscore_table.find((r) => r.parameter === parameter)
  const moduleB = data.module_b
  const traces: Partial<Data>[] = []

  if (zscoreRow) {
    traces.push({
      type: 'scatter',
      mode: 'text+markers',
      name: 'Measured (24h)',
      x: [24],
      y: [zscoreRow.value],
      text: [`${zscoreRow.value}`],
      textposition: 'top center',
      marker: { color: '#0f172a', size: 8 },
    })
    traces.push({
      type: 'scatter',
      mode: 'markers',
      name: 'Lot Median (24h)',
      x: [24],
      y: [zscoreRow.lot_median],
      marker: { color: '#94a3b8', size: 8, symbol: 'diamond' },
    })
  }

  if (moduleB && !moduleB.forecast_unavailable && moduleB.predicted_168h !== null) {
    traces.push({
      type: 'scatter',
      mode: 'text+markers',
      name: 'Module B Forecast (168h)',
      x: [168],
      y: [moduleB.predicted_168h],
      text: [`${moduleB.predicted_168h}`],
      textposition: 'top right',
      marker: { color: '#b45309', size: 10, symbol: 'square' },
      error_y:
        moduleB.interval_lower !== null && moduleB.interval_upper !== null
          ? {
              type: 'data',
              symmetric: false,
              array: [moduleB.interval_upper - moduleB.predicted_168h],
              arrayminus: [moduleB.predicted_168h - moduleB.interval_lower],
              color: '#b45309',
            }
          : undefined,
    })
    if (zscoreRow && moduleB.safety_slope !== null) {
      const safetyY168 = zscoreRow.value + moduleB.safety_slope * (168 - 24)
      traces.push({
        type: 'scatter',
        mode: 'lines',
        name: 'Safety Slope Threshold',
        x: [24, 168],
        y: [zscoreRow.value, safetyY168],
        line: { color: '#dc2626', width: 1.5, dash: 'dot' },
      })
    }
  }

  if (traces.length === 0) {
    return <p className="card-note">No trajectory data available for {parameter}.</p>
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
        xaxis: { title: { text: 'Hours' }, tickvals: [24, 168], ticktext: ['24h', '168h'] },
        yaxis: { title: { text: parameter } },
        font: { family: 'Inter, system-ui, sans-serif', size: 12, color: '#334155' },
      }}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%' }}
      useResizeHandler
    />
  )
}

function lastSignoff(history: DispositionRecord[]): DispositionRecord | null {
  if (history.length === 0) return null
  return [...history].sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1))[0]
}

type PartDetailNavState = {
  lotId?: string
  verdict?: 'PASS' | 'WATCH' | 'REJECT'
} | null

/** E6 screen 4, opened from either ranked list on the Lot Dashboard. */
export function PartDetailScreen() {
  const { componentId } = useParams()
  const navState = useLocation().state as PartDetailNavState

  if (!componentId) {
    return (
      <section className="screen">
        <h1 className="screen-title">Part Detail</h1>
        <p className="card-note">No component selected.</p>
      </section>
    )
  }

  // Keyed by componentId: clicking from one part to another (e.g. a different row in a Lot
  // Dashboard ranked list) would otherwise re-render this same component instance rather than
  // remount it, leaving an unsent rationale, an open confirmed-outcome form, or a stale
  // disposition/confirmed-outcome error from the PREVIOUS part carried over - and submittable
  // against the new one. A fresh key remounts with fresh state instead of needing an effect to
  // reset it by hand.
  return <PartDetailForComponent key={componentId} componentId={componentId} navState={navState} />
}

function PartDetailForComponent({
  componentId,
  navState,
}: {
  componentId: string
  navState: PartDetailNavState
}) {
  const client = useApiClient()
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
    queryKey: ['part-detail', componentId, navState?.lotId],
    queryFn: () => getPartDetail(client, componentId, navState?.lotId),
  })

  const queryKey = ['part-detail', componentId, navState?.lotId]

  const disposition = useMutation({
    mutationFn: (verdict: 'ACCEPT' | 'HOLD' | 'REJECT') =>
      submitDisposition(componentId, { verdict, rationale: rationale.trim() }, accountId),
    onSuccess: () => {
      setRationale('')
      void queryClient.invalidateQueries({ queryKey })
    },
  })

  const confirmedOutcomeMutation = useMutation({
    mutationFn: () =>
      submitConfirmedOutcome(
        client,
        componentId,
        { confirmed_outcome: confirmedOutcome, note: confirmedNote.trim() || null },
        navState?.lotId,
      ),
    onSuccess: () => {
      setConfirmedNote('')
      setShowConfirmedOutcome(false)
      void queryClient.invalidateQueries({ queryKey })
      void queryClient.invalidateQueries({ queryKey: WORKLIST_QUERY_KEY })
    },
  })

  const rationaleId = useId()
  const outcomeId = useId()
  const noteId = useId()

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
  const lotId = data.module_a?.lot_id ?? data.module_b?.lot_id ?? navState?.lotId ?? null
  const parameter = primaryParameter(data)
  const signoff = lastSignoff(data.disposition_history)
  const signoffAccount = TEMP_LOGIN_ACCOUNTS.find((a) => a.account_id === signoff?.account_id)
  const disabledForm = disposition.isPending || rationale.trim() === ''
  const confidenceQualifier = data.confidence_qualifier.trim()
  const zscoreRows = data.explanation?.zscore_table ?? []
  const mcdRows = data.explanation?.mcd_contributions ?? []
  const ecodRows = data.explanation?.ecod_dimensions ?? []
  const shapRows = data.explanation?.shap_contributions ?? []

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
            <h1 className="screen-title">{parameter ?? 'No Parameter Flagged'}</h1>
          </div>
        </div>
        {navState?.verdict ? (
          <VerdictBadge verdict={navState.verdict} />
        ) : (
          <span className="muted">Verdict unavailable</span>
        )}
      </header>
      <p className="part-detail-lot">
        LOT:{' '}
        {lotId ? (
          <Link to={pathToLot(lotId)} className="mono">
            {lotId}
          </Link>
        ) : (
          <span className="muted">unavailable</span>
        )}
      </p>

      {data.severity_cap_note && (
        <NoteCard title="Explainability Gate Severity-Cap Applied" text={data.severity_cap_note} />
      )}
      {data.unavailable_forecast_note && (
        <NoteCard title="Drift Prediction Unavailable" text={data.unavailable_forecast_note} />
      )}
      {data.staleness_note && (
        <NoteCard title="Analysis Run Stale Notice" text={data.staleness_note} tone="stale" />
      )}

      <div className="part-detail-grid">
        <section className="card trajectory-card" aria-label="Burn-in parameter trajectory">
          <header className="card-header">
            <div>
              <h2 className="card-title">
                Burn-In Parameter Trajectory (24h Measured
                {data.module_b && !data.module_b.forecast_unavailable
                  ? ' & Module B Forecast'
                  : ''}
                )
              </h2>
              {parameter && <p className="card-subtitle">Parameter: {parameter}</p>}
            </div>
          </header>
          {!data.module_b ? (
            <ModuleUnavailable module="B" />
          ) : data.unavailable_forecast_note ? (
            <p className="card-note">{data.unavailable_forecast_note}</p>
          ) : parameter ? (
            <TrajectoryChart data={data} parameter={parameter} />
          ) : (
            <p className="card-note">No parameter flagged for this part.</p>
          )}
        </section>

        <div className="part-detail-side">
          <section className="card diagnostic-card" aria-label="Diagnostic explanation">
            <header className="card-header">
              <h2 className="card-title">Diagnostic Explanation</h2>
              {confidenceQualifier && (
                <span className="chip confidence-chip">{confidenceQualifier}</span>
              )}
            </header>
            <p className="diagnostic-text">{data.explanation_sentence}</p>
          </section>

          {!data.module_b ? (
            <section className="card" aria-label="Model vs physics disagreement">
              <ModuleUnavailable module="B" />
            </section>
          ) : (
            !data.module_b.forecast_unavailable && (
              <section
                className="card disagreement-card"
                aria-label="Model vs physics disagreement"
              >
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
                      {data.module_b.physics_baseline_prediction === null
                        ? '—'
                        : data.module_b.physics_baseline_prediction}
                    </p>
                    <p className="muted">Power-law extrapolation baseline</p>
                  </div>
                  <div>
                    <p className="summary-label">Live ML Model</p>
                    <p className="mono disagreement-value">
                      {data.module_b.predicted_168h === null ? '—' : data.module_b.predicted_168h}
                    </p>
                    <p className="muted">Gradient-boosted regression</p>
                  </div>
                </div>
                <div className="disagreement-net">
                  <p className="summary-label">Net Disagreement Gap</p>
                  <p className="mono">
                    {data.module_b.physics_disagreement_gap === null
                      ? '—'
                      : `${data.module_b.physics_disagreement_gap >= 0 ? '+' : ''}${data.module_b.physics_disagreement_gap}`}
                  </p>
                </div>
              </section>
            )
          )}

          {data.module_b && <ShapCard rows={shapRows} />}
        </div>
      </div>

      <ZScoreTable rows={zscoreRows} />

      {!data.module_a ? (
        <section className="card" aria-label="Module A contribution">
          <ModuleUnavailable module="A" />
        </section>
      ) : (
        (mcdRows.length > 0 || ecodRows.length > 0) && (
          <div className="contribution-grid">
            <McdCard dSquared={data.module_a.mcd_distance} rows={mcdRows} />
            <EcodCard oScore={data.module_a.ecod_score} rows={ecodRows} />
          </div>
        )
      )}

      <section className="card disposition-card" aria-label="Disposition">
        <header className="disposition-header">
          <div>
            <h2 className="card-title">{parameter ?? 'Disposition'}</h2>
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
