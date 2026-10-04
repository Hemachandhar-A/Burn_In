import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { Data } from 'plotly.js'
import { useId, useState } from 'react'
import RawPlot from 'react-plotly.js'
import { Link, useLocation, useParams } from 'react-router-dom'
import { useApiClient } from '../api/ApiClientContext'
import { displayNameFor } from '../auth/accounts'
import { describeFailure } from '../api/errors'
import { getPartDetail, submitConfirmedOutcome, submitDisposition } from '../api/parts'
import type { PartDetailResponse } from '../api/parts'
import type { components } from '../api/schema'
import { WORKLIST_QUERY_KEY } from '../api/settings'
import { formatQuantity, scaleFor, scaleForSeries } from '../format/units'
import { pathToLot } from './registry'
import { formatNumber, formatUtc } from './settingsFormat'
import { DispositionStatusBadge } from './DispositionStatusBadge'
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

/** A number through formatNumber, with an explicit sign for signed quantities; a value formatNumber
 * rejects (NaN/Infinity) is a dash, never the raw number. */
function fmt(value: number | null | undefined, signed = false): string {
  const text = formatNumber(value)
  if (text === null) return '—'
  return signed && value !== null && value !== undefined && value >= 0 ? `+${text}` : text
}

function formatTimestamp(iso: string): string {
  return formatUtc(iso).slice(0, 16)
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
function McdCard({
  dSquared,
  rows,
  usedForFlag,
}: {
  dSquared: number | null
  rows: MCDContributionRow[]
  usedForFlag: boolean
}) {
  if (rows.length === 0) return null
  const total = rows.reduce((sum, r) => sum + Math.max(0, r.contribution), 0)
  return (
    <section className="card contribution-card" aria-label="MCD parameter contribution">
      <header className="card-header">
        <div>
          <h2 className="card-title">MCD Parameter Contribution</h2>
          <p className="card-subtitle">
            {usedForFlag
              ? 'Minimum Covariance Determinant (Mahalanobis distance share)'
              : 'Multivariate view (not used for the flag at this lot size)'}
          </p>
        </div>
        {usedForFlag && <span className="chip mono">D² = {fmt(dSquared)}</span>}
      </header>
      <div className="contribution-list">
        {rows.map((row) => (
          <ContributionBar
            key={row.parameter}
            label={row.parameter}
            valueText={fmt(row.contribution)}
            pct={total > 0 ? (Math.max(0, row.contribution) / total) * 100 : 0}
          />
        ))}
      </div>
    </section>
  )
}

function EcodCard({
  oScore,
  rows,
  usedForFlag,
}: {
  oScore: number | null
  rows: EcodDimensionRow[]
  usedForFlag: boolean
}) {
  if (rows.length === 0) return null
  const max = Math.max(...rows.map((r) => r.score), 0.01)
  return (
    <section className="card contribution-card" aria-label="ECOD dimension score">
      <header className="card-header">
        <div>
          <h2 className="card-title">ECOD Dimension Score</h2>
          <p className="card-subtitle">
            {usedForFlag
              ? 'Empirical Cumulative Distribution Outlier Detection'
              : 'Distribution-free view (not used for the flag)'}
          </p>
        </div>
        {usedForFlag && <span className="chip mono">O_score = {fmt(oScore)}</span>}
      </header>
      <div className="contribution-list">
        {rows.map((row) => (
          <ContributionBar
            key={row.dimension}
            label={row.dimension}
            valueText={`score = ${fmt(row.score)}`}
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
            sublabel={row.value === null ? 'not available yet' : (formatNumber(row.value) ?? String(row.value))}
            valueText={fmt(row.shap_value, true)}
            pct={(Math.abs(row.shap_value) / max) * 100}
          />
        ))}
      </div>
    </section>
  )
}

/**
 * The checkpoint the z-score table is computed at. A constant for now: the response carries no
 * field naming it. Block 5F switches this to the backend field once it is merged.
 */
const ZSCORE_CHECKPOINT_HOURS = 24

/** One row of the z-score table with its value and lot median in the row's own display unit (an
 * automatic SI prefix, format/units.ts); a row with no unit (an older stored result) is left as it is. */
function displayRow(row: ZScoreTableRow) {
  const scale = scaleFor(Math.max(Math.abs(row.value), Math.abs(row.lot_median)), row.unit)
  return {
    unit: scale.unit,
    value: row.value / scale.factor,
    median: row.lot_median / scale.factor,
  }
}

function ZScoreTable({ rows }: { rows: ZScoreTableRow[] }) {
  if (rows.length === 0) return null
  const shown = rows.map((row) => ({ row, ...displayRow(row) }))
  const units = [...new Set(shown.map((r) => r.unit).filter((u) => u !== ''))]
  const unitText = units.length > 0 ? `, ${units.join(' / ')}` : ''
  const perRowUnits = units.length > 1
  return (
    <section className="card drift-matrix" aria-label={`${ZSCORE_CHECKPOINT_HOURS}h z-score table`}>
      <header className="card-header">
        <h2 className="card-title">{ZSCORE_CHECKPOINT_HOURS}h Z-Score Table</h2>
        <span className="card-aside">METHOD: ROBUST MEDIAN ABSOLUTE DEVIATION (MAD)</span>
      </header>
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Parameter</th>
            <th scope="col" className="numeric">
              Value ({ZSCORE_CHECKPOINT_HOURS}h{unitText})
            </th>
            <th scope="col" className="numeric">
              Lot Median ({ZSCORE_CHECKPOINT_HOURS}h{unitText})
            </th>
            <th scope="col" className="numeric">
              Robust Z-Score
            </th>
          </tr>
        </thead>
        <tbody>
          {shown.map(({ row, unit, value, median }) => (
            <tr key={row.parameter} className={Math.abs(row.z) >= 3 ? 'row-elevated' : ''}>
              <td>
                {row.parameter}
                {perRowUnits && unit !== '' ? ` (${unit})` : ''}
              </td>
              <td className="mono numeric">{formatNumber(value) ?? value}</td>
              <td className="mono numeric muted">{formatNumber(median) ?? median}</td>
              <td className="mono numeric">
                {fmt(row.z, true)} σ
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

type MeasuredPoint = { hour: number; value: number; lotMedian: number | null }

/**
 * Measured points at every checkpoint the backend returns (`explanation.trajectory`); a part with
 * no stored trajectory (a PASS part, or a run stored before Block 4c) falls back to the one 24h
 * point the z-score table carries, so the chart never claims checkpoints it wasn't given.
 */
function measuredPoints(data: PartDetailResponse, parameter: string): MeasuredPoint[] {
  const trajectory = data.explanation?.trajectory ?? []
  if (trajectory.length > 0) {
    return [...trajectory]
      .sort((a, b) => a.checkpoint_hour - b.checkpoint_hour)
      .map((p) => ({ hour: p.checkpoint_hour, value: p.value, lotMedian: p.lot_median ?? null }))
  }
  const row = data.explanation?.zscore_table.find((r) => r.parameter === parameter)
  return row ? [{ hour: 24, value: row.value, lotMedian: row.lot_median }] : []
}

function label(value: number): string {
  return formatNumber(value) ?? ''
}

/** Whether Module B has a usable 168h forecast to draw (rule 7: never a guessed one). */
function forecastOf(data: PartDetailResponse) {
  const b = data.module_b
  if (!b || b.forecast_unavailable || b.predicted_168h === null) return null
  return b
}

/** The canonical unit of the part's worst parameter: the trajectory's own, else the z-score row's, else the
 * forecast's. None on an older stored result - then the chart simply carries no unit. */
function unitOf(data: PartDetailResponse, parameter: string): string | null {
  const fromTrajectory = data.explanation?.trajectory.find((p) => p.unit)?.unit
  const fromZ = data.explanation?.zscore_table.find((r) => r.parameter === parameter && r.unit)?.unit
  return fromTrajectory ?? fromZ ?? data.module_b?.unit ?? null
}

function TrajectoryChart({
  data,
  parameter,
  measured: measuredCanonical,
}: {
  data: PartDetailResponse
  parameter: string
  measured: MeasuredPoint[]
}) {
  const forecast = forecastOf(data)
  const traces: Partial<Data>[] = []
  // One display scale for the whole y axis, from the largest value on it (10000 nA is drawn as 10 uA).
  const unit = unitOf(data, parameter)
  const slopeEnd = (() => {
    const anchor = measuredCanonical.find((p) => p.hour === 24)
    return anchor && forecast && forecast.safety_slope !== null
      ? anchor.value + forecast.safety_slope * (168 - 24)
      : null
  })()
  const scale = scaleForSeries(
    [
      ...measuredCanonical.flatMap((p) => [p.value, p.lotMedian]),
      forecast?.predicted_168h,
      forecast?.interval_lower,
      forecast?.interval_upper,
      slopeEnd,
    ],
    unit,
  )
  const measured = measuredCanonical.map((p) => ({
    ...p,
    value: p.value / scale.factor,
    lotMedian: p.lotMedian === null ? null : p.lotMedian / scale.factor,
  }))

  if (measured.length > 0) {
    traces.push({
      type: 'scatter',
      mode: 'text+lines+markers',
      name: 'Measured',
      x: measured.map((p) => p.hour),
      y: measured.map((p) => p.value),
      text: measured.map((p) => label(p.value)),
      textposition: 'top left',
      line: { color: '#0f172a', width: 1.5 },
      marker: { color: '#0f172a', size: 8 },
    })
    const withMedian = measured.filter((p) => p.lotMedian !== null)
    if (withMedian.length > 0) {
      traces.push({
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Lot Median',
        x: withMedian.map((p) => p.hour),
        y: withMedian.map((p) => p.lotMedian),
        line: { color: '#94a3b8', width: 1.5, dash: 'dash' },
        marker: { color: '#94a3b8', size: 7, symbol: 'diamond' },
      })
    }
  }

  if (forecast && forecast.predicted_168h !== null) {
    const predicted = forecast.predicted_168h / scale.factor
    traces.push({
      type: 'scatter',
      mode: 'text+markers',
      name: 'Module B Forecast (168h)',
      x: [168],
      y: [predicted],
      text: [label(predicted)],
      textposition: 'middle right',
      marker: { color: '#b45309', size: 10, symbol: 'square' },
      error_y:
        forecast.interval_lower !== null && forecast.interval_upper !== null
          ? {
              type: 'data',
              symmetric: false,
              array: [forecast.interval_upper / scale.factor - predicted],
              arrayminus: [predicted - forecast.interval_lower / scale.factor],
              color: '#b45309',
            }
          : undefined,
    })
    const anchor = measured.find((p) => p.hour === 24)
    if (anchor && forecast.safety_slope !== null) {
      traces.push({
        type: 'scatter',
        mode: 'lines',
        name: 'Safety Slope Threshold',
        x: [24, 168],
        y: [anchor.value, anchor.value + (forecast.safety_slope * (168 - 24)) / scale.factor],
        line: { color: '#dc2626', width: 1.5, dash: 'dot' },
      })
    }
  }

  if (traces.length === 0) {
    return <p className="card-note">No trajectory data available for {parameter}.</p>
  }

  const hours = [...new Set([...measured.map((p) => p.hour), ...(forecast ? [168] : [])])].sort(
    (a, b) => a - b,
  )

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
          title: { text: 'Hours' },
          range: [-16, hours[hours.length - 1] + 30],
          tickvals: hours,
          ticktext: hours.map((h) => `${h}h`),
        },
        yaxis: { title: { text: scale.unit ? `${parameter} (${scale.unit})` : parameter } },
        font: { family: 'Inter, system-ui, sans-serif', size: 12, color: '#334155' },
      }}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%' }}
      useResizeHandler
    />
  )
}

function sortedSignoffs(history: DispositionRecord[]): DispositionRecord[] {
  return [...history].sort((a, b) => (a.timestamp < b.timestamp ? -1 : a.timestamp > b.timestamp ? 1 : 0))
}

/** What the backend history actually says: a list of sign-offs and how many distinct accounts made
 * them. The backend has no "finalized" state for a part disposition, so none is shown. */
function SignoffHistory({ history }: { history: DispositionRecord[] }) {
  if (history.length === 0) return <p className="card-note">No sign-offs recorded yet.</p>
  const distinct = new Set(history.map((h) => h.account_id)).size
  return (
    <div className="signoff-history" aria-label="Sign-off history">
      <p className="summary-label">
        {distinct} sign-off(s) recorded by distinct accounts
      </p>
      <ul className="signoff-list">
        {sortedSignoffs(history).map((h, i) => (
          <li key={i}>
            <VerdictBadge verdict={h.verdict} /> by{' '}
            <span className="mono">{h.account_id}</span> ({displayNameFor(h.account_id)}) on{' '}
            <span className="mono">{formatUtc(h.timestamp)}</span> UTC · run{' '}
            <span className="mono">{h.analysis_run_id}</span>
            {h.rationale && <span className="muted"> — {h.rationale}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Only the lot is read from navigation state, and only as the route's documented `lot_id`
 * query parameter that disambiguates a component_id reused across lots; everything displayed
 * comes from the response. */
type PartDetailNavState = { lotId?: string } | null

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
  const queryClient = useQueryClient()

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
    mutationFn: (verdict: 'ACCEPT' | 'HOLD' | 'REJECT') => {
      const projectId = detail.data?.project_id
      const analysisRunId = detail.data?.analysis_run_id
      if (!projectId || !analysisRunId)
        return Promise.reject(new Error('This part response carries no project or analysis run.'))
      return submitDisposition(
        client,
        detail.data?.component_id ?? componentId,
        { projectId, analysisRunId },
        { verdict, rationale: rationale.trim() },
      )
    },
    onSuccess: () => {
      setRationale('')
      void queryClient.invalidateQueries({ queryKey })
      void queryClient.invalidateQueries({ queryKey: WORKLIST_QUERY_KEY })
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
  const lotId = data.lot_id ?? null
  const shownComponentId = data.component_id ?? componentId
  const parameter = primaryParameter(data)
  const measured = measuredPoints(data, parameter ?? '')
  const canSubmit = Boolean(data.project_id && data.analysis_run_id)
  const disabledForm = disposition.isPending || !canSubmit || rationale.trim() === ''
  const confidenceQualifier = data.confidence_qualifier.trim()
  const zscoreRows = data.explanation?.zscore_table ?? []
  const mcdRows = data.explanation?.mcd_contributions ?? []
  const ecodRows = data.explanation?.ecod_dimensions ?? []
  const shapRows = data.explanation?.shap_contributions ?? []
  // Absolute scoring (V1F) sets severity_log10p: the flag then comes from the robust-z leg and, for lots of 77+ parts, the MCD leg
  // (explainable_tags.mcd); ECOD never scores. Legacy rank scoring has no severity_log10p and uses every detector.
  const absoluteScoring = data.module_a?.severity_log10p != null
  const mcdUsedForFlag = !absoluteScoring || Boolean(data.module_a?.explainable_tags?.mcd)
  const ecodUsedForFlag = !absoluteScoring

  return (
    <section className="screen part-detail">
      <code data-testid="route-id" className="visually-hidden">
        {componentId}
      </code>
      <header className="part-detail-header">
        <div className="part-detail-heading">
          <span className="chip">
            DUT IDENTIFIER <span className="mono">{shownComponentId}</span>
          </span>
          <div>
            <p className="summary-label">Primary Target Parameter</p>
            <h1 className="screen-title">{parameter ?? 'No Parameter Flagged'}</h1>
          </div>
        </div>
        {data.verdict ? (
          <VerdictBadge verdict={data.verdict} />
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
      {data.module_b_advisory_note && (
        <NoteCard title="Module B Forecast (Information Only)" text={data.module_b_advisory_note} />
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
                Burn-In Parameter Trajectory (Measured
                {forecastOf(data) ? ' & Module B Forecast' : ''})
              </h2>
              {parameter && <p className="card-subtitle">Parameter: {parameter}</p>}
            </div>
          </header>
          {measured.length === 0 && !forecastOf(data) ? (
            !data.module_b ? (
              <ModuleUnavailable module="B" />
            ) : data.unavailable_forecast_note ? (
              <p className="card-note">{data.unavailable_forecast_note}</p>
            ) : (
              <p className="card-note">No trajectory data available for this part.</p>
            )
          ) : (
            <>
              {data.unavailable_forecast_note && (
                <p className="card-note">{data.unavailable_forecast_note}</p>
              )}
              <TrajectoryChart data={data} parameter={parameter ?? ''} measured={measured} />
            </>
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
                      {formatQuantity(data.module_b.physics_baseline_prediction, data.module_b.unit)}
                    </p>
                    <p className="muted">Power-law extrapolation baseline</p>
                  </div>
                  <div>
                    <p className="summary-label">Live ML Model</p>
                    <p className="mono disagreement-value">
                      {formatQuantity(data.module_b.predicted_168h, data.module_b.unit)}
                    </p>
                    <p className="muted">Gradient-boosted regression</p>
                  </div>
                </div>
                <div className="disagreement-net">
                  <p className="summary-label">Net Disagreement Gap</p>
                  <p className="mono">
                    {data.module_b.physics_disagreement_gap === null
                      ? '—'
                      : `${data.module_b.physics_disagreement_gap >= 0 ? '+' : ''}${formatQuantity(data.module_b.physics_disagreement_gap, data.module_b.unit)}`}
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
            <McdCard dSquared={data.module_a.mcd_distance} rows={mcdRows} usedForFlag={mcdUsedForFlag} />
            <EcodCard oScore={data.module_a.ecod_score} rows={ecodRows} usedForFlag={ecodUsedForFlag} />
          </div>
        )
      )}

      <section className="card disposition-card" aria-label="Disposition">
        <header className="disposition-header">
          <div>
            <h2 className="card-title">{parameter ?? 'Disposition'}</h2>
            <p className="card-subtitle">
              Record reviewer Accept / Hold for Retest / Reject decision and technical disposition
              rationale. A written rationale is required for every decision; a Reject needs two
              distinct accounts.
            </p>
          </div>
          <DispositionStatusBadge status={data.disposition_status} />
        </header>

        <SignoffHistory history={data.disposition_history} />

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
          Technical Disposition Rationale (required)
        </label>
        <textarea
          id={rationaleId}
          className="input disposition-textarea"
          required
          aria-required="true"
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
