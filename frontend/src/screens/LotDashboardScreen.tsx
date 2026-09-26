import { useMutation, useQuery } from '@tanstack/react-query'
import { useId, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useApiClient } from '../api/ApiClientContext'
import { describeFailure } from '../api/errors'
import { downloadReport, generateDpaWorkOrder, getLotSummary } from '../api/lotDetail'
import type {
  MOCK_DPAWorkOrderResponse,
  MOCK_RiskAssessment,
  TEMP_LotSummaryResponse,
} from '../api/mocks'
import { BarChartIcon, ClipboardIcon, DownloadIcon, TrendUpIcon } from '../shell/icons'
import { pathToPart } from './registry'
import { VerdictBadge } from './VerdictBadge'

/** Non-PASS assessments - `assessments` isn't documented as flagged-only, so this never assumes it. */
function flaggedAssessments(data: TEMP_LotSummaryResponse): MOCK_RiskAssessment[] {
  return data.assessments.filter((a) => a.verdict !== 'PASS')
}

/** E4 step 7: a template over already-computed per-part outputs, not a new model. */
function lotLevelSummary(data: TEMP_LotSummaryResponse): string {
  const flagged = flaggedAssessments(data)
  if (flagged.length === 0) return `0 of ${data.lot_size} parts flagged. Lot is clean.`
  const counts = new Map<string, number>()
  for (const a of flagged) counts.set(a.worst_parameter, (counts.get(a.worst_parameter) ?? 0) + 1)
  const topParameter = [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0]
  const reviewCount = flagged.filter((a) => a.verdict === 'WATCH').length
  const rejectCount = flagged.filter((a) => a.verdict === 'REJECT').length
  const parts: string[] = []
  if (reviewCount > 0) parts.push(`${reviewCount} crossing REVIEW`)
  if (rejectCount > 0) parts.push(`${rejectCount} crossing REJECT`)
  const tail = parts.length > 0 ? `, ${parts.join(' and ')}` : ''
  return `${flagged.length} of ${data.lot_size} parts flagged, concentrated in ${topParameter.toLowerCase()}${tail}.`
}

function RankedList({
  title,
  icon,
  countLabel,
  rows,
}: {
  title: string
  icon: ReactNode
  countLabel: string
  rows: MOCK_RiskAssessment[]
}) {
  const headingId = useId()
  return (
    <section className="card ranked-list" aria-labelledby={headingId}>
      <header className="card-header">
        <h2 className="card-title" id={headingId}>
          {icon}
          {title}
        </h2>
        <span className="card-aside">
          N={rows.length} {countLabel}
        </span>
      </header>
      {rows.length === 0 ? (
        <p className="card-note">No parts flagged by this module.</p>
      ) : (
        <table className="table" aria-labelledby={headingId}>
          <thead>
            <tr>
              <th scope="col">Component ID</th>
              <th scope="col">Parameter Name</th>
              <th scope="col" className="numeric">
                Severity
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.component_id}>
                <td className="mono">
                  <Link
                    to={pathToPart(row.component_id)}
                    state={{
                      lotId: row.lot_id,
                      verdict: row.verdict,
                      worstParameter: row.worst_parameter,
                    }}
                  >
                    {row.component_id}
                  </Link>
                </td>
                <td>{row.worst_parameter}</td>
                <td className="numeric">
                  <VerdictBadge verdict={row.verdict} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

function DpaResultPanel({ result }: { result: MOCK_DPAWorkOrderResponse }) {
  return (
    <section className="card dpa-result" aria-label="DPA work order">
      <header className="card-header">
        <h2 className="card-title">
          <ClipboardIcon />
          DPA Work Order
        </h2>
        <span className="card-aside">{result.recommendations.length} of 3 recommended</span>
      </header>
      <ul className="dpa-list">
        {result.recommendations.map((rec) => (
          <li key={rec.component_id}>
            <Link to={pathToPart(rec.component_id)} className="mono dpa-component">
              {rec.component_id}
            </Link>
            <span className="dpa-reason">{rec.reason}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** E6 screen 3: Early-Check (In-Progress, Module B only) or Full Disposition (Complete, both). */
export function LotDashboardScreen() {
  const { lotId } = useParams()

  if (!lotId) {
    return (
      <section className="screen">
        <h1 className="screen-title">Lot Dashboard</h1>
        <p className="card-note">No lot selected.</p>
      </section>
    )
  }

  // Keyed by lotId: navigating from one lot's dashboard to another's would otherwise re-render
  // this same component instance (React Router doesn't remount for a param-only change), leaving
  // a DPA work order or a report/DPA error from the PREVIOUS lot showing under the new one's
  // data. A fresh key remounts with fresh state instead of needing an effect to reset it by hand.
  return <LotDashboardForLot key={lotId} lotId={lotId} />
}

function LotDashboardForLot({ lotId }: { lotId: string }) {
  const client = useApiClient()
  const [dpaResult, setDpaResult] = useState<MOCK_DPAWorkOrderResponse | null>(null)

  const summary = useQuery({
    queryKey: ['lot-summary', lotId],
    queryFn: () => getLotSummary(lotId),
  })

  const report = useMutation({
    mutationFn: () => downloadReport(client, lotId),
    onSuccess: ({ blob, filename }) => {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    },
  })

  const dpa = useMutation({
    mutationFn: () => generateDpaWorkOrder(lotId),
    onSuccess: (result) => setDpaResult(result),
  })

  const data = summary.data
  const byModuleA = data
    ? [...data.assessments]
        .filter((a) => a.module_a_ran && a.verdict !== 'PASS')
        .sort((a, b) => b.module_a_rank - a.module_a_rank)
    : []
  const byModuleB = data
    ? [...data.assessments]
        .filter((a) => a.module_b_ran && a.verdict !== 'PASS')
        .sort((a, b) => b.module_b_rank - a.module_b_rank)
    : []

  return (
    <section className="screen lot-dashboard">
      {/* Not shown; lets a test confirm a URL-encoded lot id decoded correctly (P1.9 precedent). */}
      <code data-testid="route-id" className="visually-hidden">
        {lotId}
      </code>
      <header className="screen-header">
        <div>
          <h1 className="screen-title">Lot Dashboard</h1>
          <p className="screen-subtitle">
            Lot-level screening overview and dual-module severity triage
          </p>
        </div>
        <div className="screen-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => report.mutate()}
            disabled={!data || report.isPending}
          >
            <DownloadIcon />
            {report.isPending ? 'Generating…' : 'Generate Report'}
          </button>
          {data?.disposition.status === 'COMPLETE' && (
            <button
              type="button"
              className="button button-primary"
              onClick={() => dpa.mutate()}
              disabled={dpa.isPending}
            >
              <ClipboardIcon />
              {dpa.isPending ? 'Generating…' : 'Generate DPA Work Order'}
            </button>
          )}
        </div>
      </header>

      {summary.isPending && <p className="card-note">Loading lot summary…</p>}

      {summary.isError && (
        <div className="card-note form-error" role="alert">
          <p>Could not load this lot.</p>
          <ul className="message-list">
            {describeFailure(summary.error).map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => summary.refetch()}
            disabled={summary.isFetching}
          >
            {summary.isFetching ? 'Retrying…' : 'Retry'}
          </button>
        </div>
      )}

      {report.isError && (
        <div className="banner form-error" role="alert">
          <p className="banner-title">Report generation failed</p>
          <ul className="message-list">
            {describeFailure(report.error).map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </div>
      )}

      {dpa.isError && (
        <div className="banner form-error" role="alert">
          <p className="banner-title">DPA work order generation failed</p>
          <ul className="message-list">
            {describeFailure(dpa.error).map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </div>
      )}

      {data && (
        <>
          <section className="card lot-summary" aria-label="Lot summary">
            <div className="lot-summary-grid">
              <div>
                <p className="summary-label">Lot ID</p>
                <p className="mono summary-value">{lotId}</p>
              </div>
              <div>
                <p className="summary-label">Part Number</p>
                <p className="mono summary-value">{data.part_number}</p>
              </div>
              <div>
                <p className="summary-label">Manufacturer</p>
                <p className="summary-value">{data.manufacturer}</p>
              </div>
              <div>
                <p className="summary-label">Overall Verdict</p>
                <p className="summary-value">
                  <VerdictBadge verdict={data.disposition.verdict} />
                  {data.disposition.is_forecast && (
                    <span className="chip forecast-chip">Forecast</span>
                  )}
                </p>
              </div>
              <div>
                <p className="summary-label">Screening Summary</p>
                <p className="summary-value">
                  Flagged Parts: <span className="mono">{flaggedAssessments(data).length}</span> of{' '}
                  <span className="mono">{data.lot_size}</span>
                </p>
              </div>
              <div>
                <p className="summary-label">PDA Metric</p>
                <p className="summary-value mono">
                  PDA: {(data.disposition.pda_result * 100).toFixed(2)}%
                </p>
              </div>
            </div>
            <p className="lot-summary-note">{lotLevelSummary(data)}</p>
          </section>

          {dpaResult && <DpaResultPanel result={dpaResult} />}

          <div className="dashboard-grid">
            <RankedList
              title="By Outlier Severity"
              icon={<BarChartIcon />}
              countLabel="outliers"
              rows={byModuleA}
            />
            <RankedList
              title="By Drift Risk"
              icon={<TrendUpIcon />}
              countLabel="traces"
              rows={byModuleB}
            />
          </div>
        </>
      )}
    </section>
  )
}
