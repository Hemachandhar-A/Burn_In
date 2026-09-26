import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useApiClient } from '../api/ApiClientContext'
import { describeFailure } from '../api/errors'
import { EVENTS_QUERY_KEY } from '../api/history'
import { listProjects, PROJECTS_QUERY_KEY } from '../api/lots'
import type {
  MOCK_CorrectiveStatusResponse,
  MOCK_DispositionRecord,
  MOCK_PendingSettingChange,
  MOCK_SettingField,
  MOCK_SettingsResponse,
} from '../api/mocks'
import {
  CORRECTIVE_STATUS_QUERY_KEY,
  getCorrectiveStatus,
  getSettings,
  getWorklist,
  proposeSetting,
  SETTINGS_QUERY_KEY,
  signoffSetting,
  WORKLIST_QUERY_KEY,
} from '../api/settings'
import { useAuth } from '../auth/AuthContext'
import { displayNameFor } from '../auth/accounts'
import { PencilIcon } from '../shell/icons'
import { pathToPart } from './registry'
import {
  formatPercent,
  formatSettingValue,
  fromInputValue,
  isRatio,
  SETTING_FIELDS,
  SETTING_LABELS,
  sortableTime,
  toInputValue,
} from './settingsFormat'
import { VerdictBadge } from './VerdictBadge'

const DESCRIPTIONS: Record<MOCK_SettingField, string> = {
  fn_fp_cost_ratio:
    'Cost of a missed defect relative to a false alarm; sets the outlier threshold.',
  pda_threshold: 'Lot-level percent defective allowable.',
  confirmed_outcome_fn_ceiling:
    'Maximum false-negative rate among confirmed physical-analysis outcomes.',
}

/** contracts.py `ScreeningConfig.min_confirmed_outcomes_for_ceiling` (E13 step 6). Not served. */
const MIN_CONFIRMED_OUTCOMES = 10

function ErrorLines({ error }: { error: unknown }) {
  return (
    <ul className="message-list">
      {describeFailure(error).map((line, i) => (
        <li key={i}>{line}</li>
      ))}
    </ul>
  )
}

function SettingCard({
  field,
  settings,
  accountId,
}: {
  field: MOCK_SettingField
  settings: MOCK_SettingsResponse
  accountId: string
}) {
  const queryClient = useQueryClient()
  const headingId = useId()
  const inputId = useId()
  const errorId = useId()
  // Where focus goes next. The control that had it (Edit, Propose, Sign off) unmounts when the
  // card changes state, which would otherwise drop keyboard focus to <body>.
  const focusNext = useRef<'edit' | 'pending' | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [invalid, setInvalid] = useState<string | null>(null)

  // An entry that already carries `signed_off_by` is finalized, not pending, even if the list
  // still returns it; showing it as awaiting sign-off would offer a second sign-off on it.
  const pending: MOCK_PendingSettingChange | undefined = settings.pending_changes.find(
    (p) => p.field === field && p.signed_off_by === null,
  )
  const label = SETTING_LABELS[field]

  // Someone else's proposal arrived (refetch) while this form was open: close it, or it would
  // reopen with a stale draft the moment that proposal is finalized.
  if (pending && editing) setEditing(false)

  // A config change affects every later lot (E10 step 5): refresh the log and the live status too.
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: SETTINGS_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: EVENTS_QUERY_KEY }),
    ])

  // A 409 (someone proposed first) or 404/403 (someone signed off first) means this card shows
  // stale state: refetch so it shows what is actually true, next to the message.
  const onMutationError = () => void queryClient.invalidateQueries({ queryKey: SETTINGS_QUERY_KEY })

  const propose = useMutation({
    mutationFn: (value: number) => proposeSetting({ field, proposed_value: value }, accountId),
    onSuccess: async () => {
      focusNext.current = 'pending'
      setEditing(false)
      await refresh()
    },
    onError: onMutationError,
  })

  const signoff = useMutation({
    mutationFn: () => signoffSetting({ field }, accountId),
    onSuccess: async (next) => {
      focusNext.current = 'edit'
      queryClient.setQueryData(SETTINGS_QUERY_KEY, next)
      await refresh()
    },
    onError: onMutationError,
  })

  function startEditing() {
    setDraft(toInputValue(field, settings[field]))
    setInvalid(null)
    propose.reset()
    signoff.reset()
    setEditing(true)
  }

  function cancel() {
    setEditing(false)
    setInvalid(null)
    focusNext.current = 'edit'
  }

  function takeFocus(target: 'edit' | 'pending') {
    return (el: HTMLElement | null) => {
      if (el && focusNext.current === target) {
        focusNext.current = null
        el.focus()
      }
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    // Enter in the input submits even while the Propose button is disabled; never send twice.
    if (propose.isPending) return
    const value = fromInputValue(field, draft)
    if (value === null) {
      setInvalid(
        isRatio(field)
          ? 'Enter a number greater than 0 (the N in N:1).'
          : 'Enter a percentage greater than 0 and no more than 100.',
      )
      return
    }
    if (value === settings[field]) {
      setInvalid('That is already the current value. Enter a different value to propose.')
      return
    }
    setInvalid(null)
    propose.mutate(value)
  }

  const mine = pending?.proposed_by === accountId
  const failure = propose.error ?? signoff.error

  return (
    <section
      className={`card setting-card${pending ? ' is-pending' : ''}`}
      aria-labelledby={headingId}
    >
      <header className="setting-card-header">
        <h2 className="setting-title" id={headingId}>
          {label}
        </h2>
        {pending ? (
          <span className="pending-tag">Pending second sign-off</span>
        ) : (
          !editing && (
            <button
              ref={takeFocus('edit')}
              type="button"
              className="button button-primary button-small"
              onClick={startEditing}
              aria-label={`Edit ${label}`}
            >
              <PencilIcon />
              Edit
            </button>
          )
        )}
      </header>

      <p className="setting-value mono">{formatSettingValue(field, settings[field])}</p>
      <p className="setting-description">{DESCRIPTIONS[field]}</p>

      {pending && (
        <div className="pending-change" ref={takeFocus('pending')} tabIndex={-1}>
          <p>
            {`Proposed ${formatSettingValue(field, pending.proposed_value)} by ${displayNameFor(pending.proposed_by)}.`}{' '}
            Not in force until signed off.
          </p>
          {mine ? (
            <p className="muted">Needs a second sign-off from a different account.</p>
          ) : (
            <button
              type="button"
              className="button button-secondary button-small"
              onClick={() => signoff.mutate()}
              disabled={signoff.isPending}
            >
              {signoff.isPending ? 'Signing off…' : 'Sign off'}
            </button>
          )}
        </div>
      )}

      {editing && !pending && (
        <form className="setting-form" onSubmit={submit} noValidate>
          <label className="field-label" htmlFor={inputId}>
            Proposed {label} {isRatio(field) ? '(N:1)' : '(%)'}
          </label>
          <input
            id={inputId}
            className="input mono"
            type="text"
            inputMode="decimal"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            aria-invalid={invalid ? 'true' : undefined}
            aria-describedby={invalid ? errorId : undefined}
            autoFocus
          />
          {invalid && (
            <p className="field-error" id={errorId} role="alert">
              {invalid}
            </p>
          )}
          <p className="setting-form-note">
            Becomes a pending change. A second, different account has to sign off before it applies.
          </p>
          <div className="setting-form-actions">
            <button
              type="submit"
              className="button button-primary button-small"
              disabled={propose.isPending}
            >
              {propose.isPending ? 'Proposing…' : 'Propose'}
            </button>
            <button type="button" className="button button-secondary button-small" onClick={cancel}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {failure && (
        <div className="form-error setting-error" role="alert">
          <ErrorLines error={failure} />
        </div>
      )}
    </section>
  )
}

const STATUS_TIER: Record<MOCK_CorrectiveStatusResponse['status'], string> = {
  OK: 'badge-pass',
  INSUFFICIENT_DATA: 'badge-watch',
  CEILING_EXCEEDED: 'badge-reject',
}

function CorrectiveStatus({ ceiling }: { ceiling: number | undefined }) {
  const headingId = useId()
  // E13 step 7: recalculated whenever the screen is viewed, never a stored alert.
  const status = useQuery({
    queryKey: CORRECTIVE_STATUS_QUERY_KEY,
    queryFn: () => getCorrectiveStatus(),
    refetchOnMount: 'always',
  })
  const data = status.data

  return (
    <section className="card corrective" aria-labelledby={headingId}>
      <header className="card-header card-header-stacked">
        <h2 className="card-title" id={headingId}>
          Corrective Feedback Status
        </h2>
        <p className="card-subtitle">
          Computed live from confirmed physical-analysis outcomes each time this screen opens.
        </p>
      </header>
      {status.isPending && <p className="card-note">Computing…</p>}
      {status.isError && data && <StaleNote what="the corrective status" />}
      {status.isError && !data && (
        <div className="card-note form-error" role="alert">
          <ErrorLines error={status.error} />
          <button
            type="button"
            className="button button-secondary"
            onClick={() => status.refetch()}
            disabled={status.isFetching}
          >
            Retry
          </button>
        </div>
      )}
      {data && (
        <div className="corrective-body">
          <div className="corrective-main">
            <span className={`badge corrective-current ${STATUS_TIER[data.status] ?? ''}`}>
              {data.status.replace(/_/g, ' ')}
            </span>
            <div>
              <p className="corrective-rate">
                FN rate <span className="mono">{formatPercent(data.fn_rate)}</span>{' '}
                <span className="muted">(N={data.confirmed_outcome_count} confirmed outcomes)</span>
              </p>
              <p className="corrective-context">
                FP rate <span className="mono">{formatPercent(data.fp_rate)}</span>, shown for
                context only, never a trigger.
              </p>
              {data.status === 'INSUFFICIENT_DATA' && (
                <p className="corrective-note">
                  Fewer than {MIN_CONFIRMED_OUTCOMES} confirmed outcomes: the ceiling isn't active
                  yet.
                </p>
              )}
              {data.status === 'CEILING_EXCEEDED' && (
                <p className="corrective-note">
                  FN rate is above the{' '}
                  {ceiling === undefined ? 'configured' : formatPercent(ceiling)} ceiling. Any
                  threshold change goes through the same dual sign-off above.
                </p>
              )}
            </div>
          </div>
          <p className="corrective-legend">
            <span>States:</span>
            {(['OK', 'INSUFFICIENT_DATA', 'CEILING_EXCEEDED'] as const).map((s) => (
              <span key={s} className="legend-chip">
                {s.replace(/_/g, ' ')}
              </span>
            ))}
          </p>
        </div>
      )}
    </section>
  )
}

/** Whole days since `iso`; a future timestamp (clock skew) is 0; an unparseable one is null. */
function daysSince(iso: string): number | null {
  const at = sortableTime(iso)
  if (at === -Infinity) return null
  return Math.max(0, Math.floor((Date.now() - at) / 86_400_000))
}

/** A background refetch failed but earlier data is still on screen: say it may be out of date. */
function StaleNote({ what }: { what: string }) {
  return (
    <p className="card-note stale-note" role="status">
      Could not refresh {what}; showing what was last loaded.
    </p>
  )
}

/**
 * One row per part. The route returns dispositions with no confirmed outcome yet, and a dual
 * REJECT is two sign-off records for the same part (two rows, and a duplicate React key). Keeps
 * the most recent record per part, longest-waiting first.
 */
function worklistRows(pending: MOCK_DispositionRecord[]): MOCK_DispositionRecord[] {
  const latest = new Map<string, MOCK_DispositionRecord>()
  for (const record of pending) {
    const key = JSON.stringify([record.project_id, record.component_id])
    const seen = latest.get(key)
    if (!seen || sortableTime(record.timestamp) >= sortableTime(seen.timestamp)) {
      latest.set(key, record)
    }
  }
  return [...latest.values()]
    .map((record, index) => ({ record, index, at: sortableTime(record.timestamp) }))
    .sort((a, b) => (a.at === b.at ? a.index - b.index : a.at < b.at ? -1 : 1))
    .map(({ record }) => record)
}

function Worklist() {
  const client = useApiClient()
  const headingId = useId()
  const worklist = useQuery({ queryKey: WORKLIST_QUERY_KEY, queryFn: () => getWorklist() })
  const projects = useQuery({ queryKey: PROJECTS_QUERY_KEY, queryFn: () => listProjects(client) })
  const lots = new Map((projects.data ?? []).map((p) => [p.project_id, p.lot_id]))
  const rows = worklistRows(worklist.data?.pending ?? [])

  return (
    <section className="card worklist" aria-labelledby={headingId}>
      <header className="card-header card-header-stacked">
        <h2 className="card-title" id={headingId}>
          Worklist
        </h2>
        <p className="card-subtitle">
          Dispositions awaiting a confirmed outcome from destructive physical analysis. Tracking
          only; DPA work orders are generated per lot on the Lot Dashboard.
        </p>
      </header>
      {worklist.isPending && <p className="card-note">Loading worklist…</p>}
      {worklist.isError && worklist.data && <StaleNote what="the worklist" />}
      {worklist.isError && !worklist.data && (
        <div className="card-note form-error" role="alert">
          <ErrorLines error={worklist.error} />
          <button
            type="button"
            className="button button-secondary"
            onClick={() => worklist.refetch()}
            disabled={worklist.isFetching}
          >
            Retry
          </button>
        </div>
      )}
      {worklist.data && rows.length === 0 && (
        <p className="card-note">No dispositions are awaiting a confirmed outcome.</p>
      )}
      {rows.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Component ID</th>
              <th scope="col">Lot ID</th>
              <th scope="col">Disposition</th>
              <th scope="col" className="numeric">
                Days Pending
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const lotId = lots.get(r.project_id)
              const days = daysSince(r.timestamp)
              return (
                <tr key={`${r.project_id}:${r.component_id}`}>
                  <td className="mono">
                    <Link to={pathToPart(r.component_id)} state={lotId ? { lotId } : undefined}>
                      {r.component_id}
                    </Link>
                  </td>
                  <td className="mono">{lotId ?? r.project_id}</td>
                  <td>
                    <VerdictBadge verdict={r.verdict} />
                  </td>
                  <td className="mono numeric">{days === null ? '—' : `${days}d`}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </section>
  )
}

/**
 * E6 screen 7: the three live values under dual sign-off (E10 step 5), the confirmed-outcome
 * worklist and the live-computed corrective status (E13).
 */
export function SettingsScreen() {
  const { session } = useAuth()
  const settings = useQuery({ queryKey: SETTINGS_QUERY_KEY, queryFn: () => getSettings() })

  return (
    <section className="screen settings">
      <header className="screen-header">
        <div>
          <h1 className="screen-title">Settings</h1>
          <p className="screen-subtitle">
            Global detection thresholds under dual sign-off, the confirmed-outcome worklist, and
            corrective feedback status.
          </p>
        </div>
      </header>

      {settings.isPending && <p className="card-note">Loading settings…</p>}
      {settings.isError && settings.data && <StaleNote what="settings" />}
      {settings.isError && !settings.data && (
        <div className="card-note form-error" role="alert">
          <p>Could not load settings.</p>
          <ErrorLines error={settings.error} />
          <button
            type="button"
            className="button button-secondary"
            onClick={() => settings.refetch()}
            disabled={settings.isFetching}
          >
            {settings.isFetching ? 'Retrying…' : 'Retry'}
          </button>
        </div>
      )}
      {settings.data && session && (
        <div className="settings-grid">
          {SETTING_FIELDS.map((field) => (
            <SettingCard
              key={field}
              field={field}
              settings={settings.data}
              accountId={session.accountId}
            />
          ))}
        </div>
      )}

      <CorrectiveStatus ceiling={settings.data?.confirmed_outcome_fn_ceiling} />
      <Worklist />
    </section>
  )
}
