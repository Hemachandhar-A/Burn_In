import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useApiClient } from '../api/ApiClientContext'
import { describeFailure } from '../api/errors'
import { EVENTS_QUERY_KEY } from '../api/history'
import { listProjects, PROJECTS_QUERY_KEY } from '../api/lots'
import type {
  MOCK_CorrectiveStatusResponse,
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
  parseUtc,
  SETTING_FIELDS,
  SETTING_LABELS,
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
  // Set by Cancel so the Edit button, re-mounted when the form closes, takes focus back.
  const refocusEdit = useRef(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [invalid, setInvalid] = useState<string | null>(null)

  const pending: MOCK_PendingSettingChange | undefined = settings.pending_changes.find(
    (p) => p.field === field,
  )
  const label = SETTING_LABELS[field]

  // A config change affects every later lot (E10 step 5): refresh the log and the live status too.
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: SETTINGS_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: EVENTS_QUERY_KEY }),
    ])

  const propose = useMutation({
    mutationFn: (value: number) => proposeSetting({ field, proposed_value: value }, accountId),
    onSuccess: async () => {
      setEditing(false)
      await refresh()
    },
  })

  const signoff = useMutation({
    mutationFn: () => signoffSetting({ field }, accountId),
    onSuccess: async (next) => {
      queryClient.setQueryData(SETTINGS_QUERY_KEY, next)
      await refresh()
    },
  })

  function startEditing() {
    setDraft(toInputValue(field, settings[field]))
    setInvalid(null)
    propose.reset()
    setEditing(true)
  }

  function cancel() {
    setEditing(false)
    setInvalid(null)
    refocusEdit.current = true
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    const value = fromInputValue(field, draft)
    if (value === null) {
      setInvalid(
        isRatio(field)
          ? 'Enter a number greater than 0 (the N in N:1).'
          : 'Enter a percentage greater than 0 and no more than 100.',
      )
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
              ref={(el) => {
                if (el && refocusEdit.current) {
                  refocusEdit.current = false
                  el.focus()
                }
              }}
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
        <div className="pending-change">
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
    queryFn: getCorrectiveStatus,
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
      {status.isError && (
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
            <span className={`badge corrective-current ${STATUS_TIER[data.status]}`}>
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

function daysSince(iso: string): number {
  return Math.max(0, Math.floor((Date.now() - parseUtc(iso)) / 86_400_000))
}

function Worklist() {
  const client = useApiClient()
  const headingId = useId()
  const worklist = useQuery({ queryKey: WORKLIST_QUERY_KEY, queryFn: getWorklist })
  const projects = useQuery({ queryKey: PROJECTS_QUERY_KEY, queryFn: () => listProjects(client) })
  const lots = new Map((projects.data ?? []).map((p) => [p.project_id, p.lot_id]))
  const rows = [...(worklist.data?.pending ?? [])].sort((a, b) =>
    a.timestamp === b.timestamp ? 0 : a.timestamp < b.timestamp ? -1 : 1,
  )

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
      {worklist.isError && (
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
                  <td className="mono numeric">{daysSince(r.timestamp)}d</td>
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
  const settings = useQuery({ queryKey: SETTINGS_QUERY_KEY, queryFn: getSettings })

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
      {settings.isError && (
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
