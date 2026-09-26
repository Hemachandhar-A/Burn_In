import { useQueries, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApiClient } from '../api/ApiClientContext'
import { describeFailure } from '../api/errors'
import { getLotSummary } from '../api/lotDetail'
import { listProjects, PROJECTS_QUERY_KEY, type ProjectSummary } from '../api/lots'
import { displayNameFor } from '../auth/accounts'
import { SortIcon } from '../shell/icons'
import { pathToLot, screenById } from './registry'
import { formatUtc, sortableTime } from './settingsFormat'

type SortKey = 'lot_id' | 'part_number' | 'status' | 'created_at' | 'created_by'
type Direction = 'ascending' | 'descending'

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: 'lot_id', label: 'Lot ID' },
  { key: 'part_number', label: 'Part Number' },
  { key: 'status', label: 'Status' },
  { key: 'created_at', label: 'Created Date' },
  { key: 'created_by', label: 'Created By' },
]

interface Row {
  project: ProjectSummary
  /** `LotDisposition.status` as sent, or null while loading / if it couldn't be loaded. */
  status: string | null
  statusFailed: boolean
}

/**
 * Case-insensitive and numeric-aware (LOT-9 before LOT-10), pinned to one locale so the order
 * never depends on the viewer's browser settings.
 */
const collator = new Intl.Collator('en', { numeric: true, sensitivity: 'base' })

function creatorName(accountId: string): string {
  return accountId.trim() === '' ? '' : displayNameFor(accountId)
}

function sortValue(row: Row, key: SortKey): string {
  if (key === 'status') return row.status ?? ''
  if (key === 'created_by') return creatorName(row.project.created_by)
  return row.project[key]
}

function compare(a: Row, b: Row, key: SortKey): number {
  if (key === 'created_at') {
    // By instant, not by string: timestamps can arrive with and without an offset.
    const x = sortableTime(a.project.created_at)
    const y = sortableTime(b.project.created_at)
    return x === y ? 0 : x < y ? -1 : 1
  }
  return collator.compare(sortValue(a, key), sortValue(b, key))
}

/** Stable sort: ties keep GET /projects' newest-first order. Blank values sort last either way. */
function sortRows(rows: Row[], key: SortKey, direction: Direction): Row[] {
  const sign = direction === 'ascending' ? 1 : -1
  return rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => {
      if (key !== 'created_at') {
        const blankA = sortValue(a.row, key) === ''
        const blankB = sortValue(b.row, key) === ''
        if (blankA || blankB) return blankA === blankB ? a.index - b.index : blankA ? 1 : -1
      }
      return compare(a.row, b.row, key) * sign || a.index - b.index
    })
    .map(({ row }) => row)
}

function StatusCell({ row }: { row: Row }) {
  if (row.statusFailed) return <span className="muted">Unavailable</span>
  if (row.status === null) return <span className="muted">Loading…</span>
  // Shown as sent (rule 10); underscores become spaces, same as VerdictBadge.
  return (
    <span
      className={`status-chip${row.status === 'IN_PROGRESS' ? ' status-chip-in_progress' : ''}`}
    >
      {row.status.replace(/_/g, ' ')}
    </span>
  )
}

/** E6 screen 5: every project on record; opening one reloads the Lot Dashboard for its lot. */
export function ProjectBrowserScreen() {
  const client = useApiClient()
  const [sort, setSort] = useState<{ key: SortKey; direction: Direction }>({
    key: 'created_at',
    direction: 'descending',
  })

  const projects = useQuery({ queryKey: PROJECTS_QUERY_KEY, queryFn: () => listProjects(client) })

  // TEMP: `ProjectSummary` has no status (CONTRACT_CHANGES.md, P1.12), so each row reads it from
  // its lot summary's `disposition.status` - a contracted field, one request per project. Same
  // query key as the Lot Dashboard, so opening a lot from here reuses what was just fetched.
  const statuses = useQueries({
    queries: (projects.data ?? []).map((p) => ({
      queryKey: ['lot-summary', p.lot_id],
      queryFn: () => getLotSummary(p.lot_id),
    })),
  })

  const rows: Row[] = (projects.data ?? []).map((project, i) => ({
    project,
    status: statuses[i]?.data?.disposition.status ?? null,
    // A failed background refresh keeps the last status it had rather than hiding it.
    statusFailed: (statuses[i]?.isError ?? false) && !statuses[i]?.data,
  }))
  const sorted = sortRows(rows, sort.key, sort.direction)

  function toggle(key: SortKey) {
    setSort((current) =>
      current.key === key
        ? { key, direction: current.direction === 'ascending' ? 'descending' : 'ascending' }
        : { key, direction: key === 'created_at' ? 'descending' : 'ascending' },
    )
  }

  return (
    <section className="screen project-browser">
      <header className="screen-header">
        <div>
          <h1 className="screen-title">Project Browser</h1>
          <p className="screen-subtitle">
            Every lot on record. Open one to reload its Lot Dashboard from its most recent analysis
            run.
          </p>
        </div>
      </header>

      {projects.isPending && <p className="card-note">Loading projects…</p>}

      {projects.isError && projects.data && (
        <p className="card-note stale-note" role="status">
          Could not refresh projects; showing what was last loaded.
        </p>
      )}

      {projects.isError && !projects.data && (
        <div className="card-note form-error" role="alert">
          <p>Could not load projects.</p>
          <ul className="message-list">
            {describeFailure(projects.error).map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => projects.refetch()}
            disabled={projects.isFetching}
          >
            {projects.isFetching ? 'Retrying…' : 'Retry'}
          </button>
        </div>
      )}

      {projects.data && projects.data.length === 0 && (
        <div className="card card-note">
          No projects on record yet. <Link to={screenById('ingest').path}>Ingest a lot</Link> to
          create one.
        </div>
      )}

      {rows.length > 0 && (
        <div className="card">
          <table className="table sortable-table">
            <thead>
              <tr>
                {COLUMNS.map((column) => {
                  const active = sort.key === column.key
                  return (
                    <th
                      key={column.key}
                      scope="col"
                      aria-sort={active ? sort.direction : undefined}
                    >
                      <button
                        type="button"
                        className="sort-button"
                        onClick={() => toggle(column.key)}
                      >
                        {column.label}
                        <SortIcon direction={active ? sort.direction : null} />
                      </button>
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {sorted.map((row) => (
                <tr key={row.project.project_id}>
                  <td className="mono strong">
                    <Link to={pathToLot(row.project.lot_id)}>{row.project.lot_id}</Link>
                  </td>
                  <td className="mono">{row.project.part_number}</td>
                  <td>
                    <StatusCell row={row} />
                  </td>
                  <td className="mono">{formatUtc(row.project.created_at).slice(0, 10)}</td>
                  <td>{creatorName(row.project.created_by) || <span className="muted">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
