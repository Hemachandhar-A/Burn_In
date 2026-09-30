import { useQuery } from '@tanstack/react-query'
import { useId, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useApiClient } from '../api/ApiClientContext'
import { describeFailure } from '../api/errors'
import {
  EVENTS_QUERY_KEY,
  listDispositionSignoffs,
  listEvents,
  SIGNOFFS_QUERY_KEY,
  type DispositionRecord,
  type EventResponse,
} from '../api/history'
import { listProjects, PROJECTS_QUERY_KEY } from '../api/lots'
import { displayNameFor } from '../auth/accounts'
import { ChevronDownIcon, ChevronUpIcon } from '../shell/icons'
import { pathToPart } from './registry'
import {
  formatNumber,
  formatSettingValue,
  formatUtc,
  isSettingField,
  SETTING_LABELS,
  sortableTime,
} from './settingsFormat'
import { VerdictBadge } from './VerdictBadge'

type Entry =
  | { kind: 'event'; key: string; at: number; event: EventResponse }
  | { kind: 'disposition'; key: string; at: number; record: DispositionRecord }

const TYPE_LABELS: Record<EventResponse['event_type'] | 'disposition', string> = {
  ingest: 'Ingest',
  checkpoint_add: 'Checkpoint Added',
  analysis_run: 'Analysis Run',
  config_change: 'Config Change',
  timing_flag: 'Timing Flag',
  disposition: 'Disposition',
}

/** The stored diff (storage/repository.py `_diff_analysis_results`), read defensively. */
interface Diff {
  activations: [string, string[]][]
  resolved: [string, { predicted: unknown; actual: unknown }][]
  verdicts: [string, { from: unknown; to: unknown }][]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function readDiff(payload: Record<string, unknown>): Diff | null {
  const keys = ['newly_activated_modules', 'resolved_forecasts', 'verdict_changes']
  // Recognized by its keys, not by their values being objects: a backend that sends `[]` or
  // null for "nothing changed" still sent a diff, not an unknown payload.
  if (!keys.some((k) => Object.hasOwn(payload, k))) return null
  const { newly_activated_modules: a, resolved_forecasts: r, verdict_changes: v } = payload
  return {
    activations: Object.entries(isRecord(a) ? a : {}).map(([id, modules]) => [
      id,
      Array.isArray(modules) ? modules.map(String) : [String(modules)],
    ]),
    resolved: Object.entries(isRecord(r) ? r : {}).map(([id, x]) => [
      id,
      isRecord(x) ? { predicted: x.predicted, actual: x.actual } : { predicted: x, actual: x },
    ]),
    verdicts: Object.entries(isRecord(v) ? v : {}).map(([id, x]) => [
      id,
      isRecord(x) ? { from: x.from, to: x.to } : { from: x, to: x },
    ]),
  }
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`
}

function moduleName(module: string): string {
  return module === 'module_a' ? 'Module A' : module === 'module_b' ? 'Module B' : module
}

function hours(value: unknown): string | null {
  if (!Array.isArray(value) || value.length === 0) return null
  return value.map((h) => `${String(h)}h`).join(', ')
}

/** Every key the payload has, as-is: an unrecognized shape is shown, never silently dropped. A
 * number is rounded (formatNumber, same helper the diff trace uses) so float noise from the
 * server never leaks into the log verbatim. */
function genericDescription(payload: Record<string, unknown>): string {
  const parts = Object.entries(payload).map(([k, v]) => {
    const text =
      typeof v === 'number' ? (formatNumber(v) ?? String(v)) : typeof v === 'object' ? JSON.stringify(v) : String(v)
    return `${k}: ${text}`
  })
  return parts.length > 0 ? parts.join('; ') : 'No details recorded'
}

function describeEvent(event: EventResponse, lot: string): string {
  const p = event.payload
  switch (event.event_type) {
    case 'ingest': {
      if (typeof p.part_number !== 'string') break
      const facts = [`part ${p.part_number}`]
      if (typeof p.component_count === 'number') facts.push(`${p.component_count} components`)
      const h = hours(p.checkpoint_hours)
      if (h) facts.push(`checkpoints ${h}`)
      return `Lot ${lot} ingested (${facts.join(', ')})`
    }
    case 'checkpoint_add': {
      const h = hours(p.checkpoint_hours)
      if (!h) break
      return `Added checkpoint${Array.isArray(p.checkpoint_hours) && p.checkpoint_hours.length > 1 ? 's' : ''} ${h} to ${lot}`
    }
    case 'analysis_run': {
      if (Object.keys(p).length === 0) {
        return `First analysis run for ${lot}; no prior run to compare against`
      }
      const diff = readDiff(p)
      if (!diff) break
      const counts = [
        diff.activations.length > 0 &&
          plural(
            diff.activations.reduce((n, [, m]) => n + m.length, 0),
            'module activation',
          ),
        diff.resolved.length > 0 &&
          plural(diff.resolved.length, 'forecast resolved', 'forecasts resolved'),
        diff.verdicts.length > 0 && plural(diff.verdicts.length, 'verdict change'),
      ].filter(Boolean)
      return counts.length === 0
        ? `Analysis run for ${lot}: no changes from the prior run`
        : `Analysis run for ${lot}: ${counts.join(', ')}`
    }
    case 'config_change': {
      if (!isSettingField(p.field) || typeof p.proposed_value !== 'number') break
      const label = SETTING_LABELS[p.field]
      const to = formatSettingValue(p.field, p.proposed_value)
      const from =
        typeof p.previous_value === 'number' ? formatSettingValue(p.field, p.previous_value) : null
      const change = from ? `${from} → ${to}` : `to ${to}`
      if (p.stage === 'proposed') {
        return `Proposed ${label} change ${change}, awaiting a second sign-off from a different account`
      }
      if (p.stage === 'finalized') {
        const who =
          typeof p.proposed_by === 'string' && typeof p.signed_off_by === 'string'
            ? ` (proposed by ${displayNameFor(p.proposed_by)}, signed off by ${displayNameFor(p.signed_off_by)})`
            : ''
        return `Dual sign-off completed: ${label} ${change}${who}`
      }
      break
    }
    case 'timing_flag': {
      if (typeof p.message !== 'string') break
      return p.message
    }
  }
  return genericDescription(p)
}

/** A verdict from the stored diff, verbatim; a missing one is a dash, never "undefined". */
function TraceVerdict({ verdict }: { verdict: unknown }) {
  return typeof verdict === 'string' && verdict !== '' ? (
    <VerdictBadge verdict={verdict} />
  ) : (
    <span className="muted">—</span>
  )
}

function DiffTrace({ diff, id }: { diff: Diff; id: string }) {
  const headingId = useId()
  const items: ReactNode[] = [
    ...diff.activations.flatMap(([component, modules]) =>
      modules.map((m, i) => (
        <li key={`a-${component}-${i}`}>
          <span className="trace-kind">Module activation:</span> {moduleName(m)} activated for{' '}
          <span className="mono">{component}</span>
        </li>
      )),
    ),
    ...diff.resolved.map(([component, { predicted, actual }]) => {
      const forecast = formatNumber(predicted)
      const measured = formatNumber(actual) ?? '—'
      return (
        <li key={`r-${component}`}>
          <span className="trace-kind">Prediction resolved:</span>{' '}
          <span className="mono">{component}</span>{' '}
          {forecast === null ? (
            // A part whose forecast was unavailable (E7 step 10) still gets a measured 168h.
            <>
              had no 168h forecast on record; measured <span className="mono">{measured}</span>
            </>
          ) : (
            <>
              168h forecast <span className="mono">{forecast}</span> resolved to measured{' '}
              <span className="mono">{measured}</span>
            </>
          )}
        </li>
      )
    }),
    ...diff.verdicts.map(([component, { from, to }]) => (
      <li key={`v-${component}`}>
        <span className="trace-kind">Verdict shift:</span> <span className="mono">{component}</span>{' '}
        moved from <TraceVerdict verdict={from} /> to <TraceVerdict verdict={to} />
      </li>
    )),
  ]
  return (
    <section className="diff-trace" id={id} aria-labelledby={headingId}>
      <h3 className="diff-trace-title" id={headingId}>
        Stored diff trace
      </h3>
      <ul>{items}</ul>
    </section>
  )
}

function EventRow({ entry, lotFor }: { entry: Entry; lotFor: (projectId: string) => string }) {
  const [open, setOpen] = useState(false)
  const traceId = useId()

  if (entry.kind === 'disposition') {
    const r = entry.record
    return (
      <tr>
        <td className="mono">{formatUtc(r.timestamp)}</td>
        <td>{displayNameFor(r.account_id)}</td>
        <td>
          <span className="event-type">{TYPE_LABELS.disposition}</span>
        </td>
        <td>
          <p className="event-text">
            <Link to={pathToPart(r.component_id)} className="mono">
              {r.component_id}
            </Link>{' '}
            on <span className="mono">{lotFor(r.project_id)}</span>{' '}
            <VerdictBadge verdict={r.verdict} />{' '}
            {r.rationale.trim() === '' ? (
              <span className="muted">(no rationale recorded)</span>
            ) : (
              <>“{r.rationale}”</>
            )}{' '}
            <span className="muted">
              (against analysis run <span className="mono">{r.analysis_run_id}</span>)
            </span>
          </p>
        </td>
      </tr>
    )
  }

  const event = entry.event
  const diff = event.event_type === 'analysis_run' ? readDiff(event.payload) : null
  const hasChanges =
    !!diff && diff.activations.length + diff.resolved.length + diff.verdicts.length > 0

  return (
    <>
      <tr className={open ? 'is-expanded' : undefined}>
        <td className="mono">{formatUtc(event.timestamp)}</td>
        <td>{displayNameFor(event.account_id)}</td>
        <td>
          <span className="event-type">{TYPE_LABELS[event.event_type] ?? event.event_type}</span>
        </td>
        <td>
          <div className="event-description">
            <span>{describeEvent(event, lotFor(event.project_id))}</span>
            {hasChanges && (
              <button
                type="button"
                className="link-button diff-toggle"
                aria-expanded={open}
                aria-controls={traceId}
                onClick={() => setOpen((o) => !o)}
              >
                {open ? 'Hide stored diff' : 'Show stored diff'}
                {open ? <ChevronUpIcon /> : <ChevronDownIcon />}
              </button>
            )}
          </div>
        </td>
      </tr>
      {open && diff && (
        <tr className="diff-row">
          <td colSpan={2} />
          <td colSpan={2}>
            <DiffTrace diff={diff} id={traceId} />
          </td>
        </tr>
      )}
    </>
  )
}

/** Unique React keys even if the server repeats an id: a repeat gets a `#n` suffix. */
function uniqueKeys(keys: string[]): string[] {
  const seen = new Map<string, number>()
  return keys.map((key) => {
    const n = seen.get(key) ?? 0
    seen.set(key, n + 1)
    return n === 0 ? key : `${key}#${n}`
  })
}

/**
 * Events and sign-offs as one timeline, newest first. Equal (or unparseable) timestamps keep
 * server order; an unparseable timestamp sorts as the oldest instead of scrambling the sort.
 */
function timeline(events: EventResponse[], signoffs: DispositionRecord[]): Entry[] {
  const eventKeys = uniqueKeys(events.map((e) => `e:${e.event_id}`))
  const signoffKeys = uniqueKeys(
    signoffs.map((r) => `d:${r.project_id}:${r.component_id}:${r.account_id}:${r.timestamp}`),
  )
  const all: Entry[] = [
    ...events.map((event, i): Entry => ({
      kind: 'event',
      key: eventKeys[i],
      at: sortableTime(event.timestamp),
      event,
    })),
    ...signoffs.map((record, i): Entry => ({
      kind: 'disposition',
      key: signoffKeys[i],
      at: sortableTime(record.timestamp),
      record,
    })),
  ]
  return all
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) =>
      a.entry.at === b.entry.at ? a.index - b.index : a.entry.at > b.entry.at ? -1 : 1,
    )
    .map(({ entry }) => entry)
}

/**
 * E6 screen 6: the full event and disposition log, identical for both accounts (context.md
 * 5.14) - nothing here reads who is signed in. `analysis_run` entries carry their stored diff.
 */
export function HistoryScreen() {
  const client = useApiClient()
  const events = useQuery({ queryKey: EVENTS_QUERY_KEY, queryFn: () => listEvents(client) })
  const signoffs = useQuery({
    queryKey: SIGNOFFS_QUERY_KEY,
    queryFn: () => listDispositionSignoffs(client),
  })
  // Only to name each project's lot. If it fails, the log still shows, with project ids.
  const projects = useQuery({ queryKey: PROJECTS_QUERY_KEY, queryFn: () => listProjects(client) })

  const lots = new Map((projects.data ?? []).map((p) => [p.project_id, p.lot_id]))
  const lotFor = (projectId: string) => lots.get(projectId) ?? projectId

  const failed = [events, signoffs].filter((q) => q.isError)
  // Only a complete log is shown: with one half missing, the page would present a partial log
  // as the full record. A failed background refresh keeps the last complete one, flagged stale.
  const loaded = !!events.data && !!signoffs.data
  const entries: Entry[] = loaded ? timeline(events.data ?? [], signoffs.data ?? []) : []

  return (
    <section className="screen history">
      <header className="screen-header">
        <div>
          <h1 className="screen-title">History</h1>
          <p className="screen-subtitle">
            Append-only event and disposition log across every project, the same for every account.
          </p>
        </div>
      </header>

      {failed.length === 0 && (events.isPending || signoffs.isPending) && (
        <p className="card-note">Loading history…</p>
      )}

      {failed.length > 0 && loaded && (
        <p className="card-note stale-note" role="status">
          Could not refresh the history log; showing what was last loaded.
        </p>
      )}

      {failed.length > 0 && !loaded && (
        <div className="card-note form-error" role="alert">
          <p>Could not load the history log.</p>
          <ul className="message-list">
            {failed
              .flatMap((q) => describeFailure(q.error))
              .map((line, i) => (
                <li key={i}>{line}</li>
              ))}
          </ul>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => failed.forEach((q) => void q.refetch())}
            disabled={failed.some((q) => q.isFetching)}
          >
            {failed.some((q) => q.isFetching) ? 'Retrying…' : 'Retry'}
          </button>
        </div>
      )}

      {events.data && signoffs.data && entries.length === 0 && (
        <p className="card card-note">No events on record yet.</p>
      )}

      {entries.length > 0 && (
        <div className="card">
          <table className="table history-table">
            <thead>
              <tr>
                <th scope="col">Timestamp (UTC)</th>
                <th scope="col">Account</th>
                <th scope="col">Event Type</th>
                <th scope="col">Description</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <EventRow key={entry.key} entry={entry} lotFor={lotFor} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
