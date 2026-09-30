import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState, type DragEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useApiClient } from '../api/ApiClientContext'
import { describeFailure } from '../api/errors'
import {
  ensureReadable,
  listProjects,
  loadDemoLot,
  lotIdProblem,
  PROJECTS_QUERY_KEY,
  uploadCheckpoint,
  uploadLot,
  type LotMetadata,
  type LotUploadResponse,
} from '../api/lots'
import { useAuth } from '../auth/AuthContext'
import {
  CloudUploadIcon,
  FileUploadIcon,
  HourglassIcon,
  RefreshClockIcon,
  TerminalIcon,
} from '../shell/icons'
import { useWorkingLot } from '../shell/WorkingLotContext'
import { pathToLot, screenById } from './registry'

type Field = keyof LotMetadata

const FIELDS: { key: Field; label: string; placeholder: string; type?: string }[] = [
  { key: 'lot_id', label: 'Lot ID', placeholder: 'LOT-2024-8841' },
  { key: 'part_number', label: 'Part Number', placeholder: 'AD590-JH' },
  { key: 'manufacturer', label: 'Manufacturer', placeholder: 'Analog Devices' },
  { key: 'date_code', label: 'Date Code', placeholder: '2418' },
  { key: 'test_date', label: 'Test Date', placeholder: '', type: 'date' },
]

const EMPTY_METADATA: LotMetadata = {
  lot_id: '',
  part_number: '',
  manufacturer: '',
  date_code: '',
  test_date: '',
}

/** One completed call in the last batch, for the result panel. */
interface Outcome {
  kind: 'lot' | 'checkpoint' | 'demo'
  response: LotUploadResponse
}

const OUTCOME_LABEL: Record<Outcome['kind'], string> = {
  lot: 'New lot uploaded',
  checkpoint: 'Checkpoint merged',
  demo: 'Synthetic demo lot loaded',
}

/** Why a picked file can't be used, or null. The server checks the contents (E7 step 5). */
function refuseFile(file: File): string | null {
  if (!/\.csv$/i.test(file.name)) return `${file.name} is not a .csv file.`
  if (file.size === 0) return `${file.name} is empty.`
  return null
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** How many projects Recent Ingestions lists; the Project Browser has them all. */
const RECENT_LIMIT = 10

/** A real calendar date in yyyy-mm-dd. <input type="date"> also accepts 5+ digit years. */
function isValidDate(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return false
  const [y, m, d] = match.slice(1).map(Number)
  const date = new Date(Date.UTC(y, m - 1, d))
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d
}

/** Error or info lines, index-keyed (a server can repeat a message) and scrollable when long. */
function MessageList({ lines }: { lines: string[] }) {
  return (
    <ul className="message-list">
      {lines.map((line, i) => (
        <li key={i}>{line}</li>
      ))}
    </ul>
  )
}

/** `2026-09-26T14:32:10.123` -> `2026-09-26 14:32`. Storage records UTC (datetime.now(UTC)). */
function formatTimestamp(iso: string): string {
  return iso.slice(0, 16).replace('T', ' ')
}

function Card({
  title,
  aside,
  icon,
  children,
  className = '',
}: {
  title: string
  aside?: ReactNode
  icon?: ReactNode
  children: ReactNode
  className?: string
}) {
  const headingId = useId()
  return (
    <section className={`card ${className}`} aria-labelledby={headingId}>
      <header className="card-header">
        <h2 className="card-title" id={headingId}>
          {icon}
          {title}
        </h2>
        {aside && <span className="card-aside">{aside}</span>}
      </header>
      {children}
    </section>
  )
}

/** Hidden-but-focusable file input; its visible <label> is the control people click or drop on. */
function FileInput({
  id,
  label,
  onPick,
  disabled,
}: {
  id: string
  label: string
  onPick: (file: File) => void
  disabled: boolean
}) {
  return (
    <input
      id={id}
      className="visually-hidden-input"
      type="file"
      accept=".csv,text/csv"
      aria-label={label}
      disabled={disabled}
      onChange={(event) => {
        const file = event.target.files?.[0]
        if (file) onPick(file)
        // Reset, so choosing the same file again after removing it still fires onChange.
        event.target.value = ''
      }}
    />
  )
}

function StagedFile({
  file,
  onRemove,
  disabled,
}: {
  file: File
  onRemove: () => void
  disabled: boolean
}) {
  return (
    <div className="staged-file">
      <span className="mono">{file.name}</span>
      <span className="staged-file-size">{formatBytes(file.size)}</span>
      <button
        type="button"
        className="link-button"
        onClick={onRemove}
        disabled={disabled}
        aria-label={`Remove ${file.name}`}
      >
        Remove
      </button>
    </div>
  )
}

function RecentIngestions() {
  const client = useApiClient()
  const projects = useQuery({
    queryKey: PROJECTS_QUERY_KEY,
    queryFn: () => listProjects(client),
  })
  const headingId = useId()
  const data = projects.data
  const count = data?.length
  const shown = data?.slice(0, RECENT_LIMIT) ?? []

  return (
    <section className="card recent" aria-labelledby={headingId}>
      <header className="card-header recent-header">
        <div>
          <h2 className="card-title" id={headingId}>
            Recent Ingestions
          </h2>
          <p className="card-subtitle">Registry of incoming test runs</p>
        </div>
        {count !== undefined && count > 0 && (
          <span className="chip">
            {count} {count === 1 ? 'lot' : 'lots'} on record
          </span>
        )}
      </header>

      {projects.isPending && <p className="card-note">Loading recent ingestions…</p>}

      {projects.isError && (
        <div className="card-note form-error" role="alert">
          <p>Could not load recent ingestions.</p>
          <MessageList lines={describeFailure(projects.error)} />
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

      {data && data.length === 0 && <p className="card-note">No lots on record yet.</p>}

      {/* Rows already loaded stay visible if a later refresh fails; the alert above says so. */}
      {shown.length > 0 && (
        <table className="table" aria-labelledby={headingId}>
          <thead>
            <tr>
              <th scope="col">Lot ID</th>
              <th scope="col">Part Number</th>
              <th scope="col" className="numeric">
                Uploaded (UTC)
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((p) => (
              <tr key={p.project_id}>
                <td className="mono">
                  <Link to={pathToLot(p.lot_id)}>{p.lot_id}</Link>
                </td>
                <td className="mono">{p.part_number}</td>
                <td className="mono numeric muted">{formatTimestamp(p.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {count !== undefined && count > RECENT_LIMIT && (
        <p className="card-note">
          Showing the {RECENT_LIMIT} newest.{' '}
          <Link to={screenById('projects').path}>See all {count} in Project Browser</Link>
        </p>
      )}
    </section>
  )
}

function ResultPanel({ outcomes }: { outcomes: Outcome[] }) {
  const last = outcomes[outcomes.length - 1].response
  return (
    <section className="card result" aria-label="Ingestion result">
      {outcomes.map(({ kind, response }, i) => {
        const missing = response.insufficient_data_components ?? []
        return (
          <div className="result-step" key={`${kind}-${i}`}>
            <h2 className="result-title">{OUTCOME_LABEL[kind]}</h2>
            <dl className="result-facts">
              <div>
                <dt>Lot ID</dt>
                <dd className="mono">{response.lot_id}</dd>
              </div>
              <div>
                <dt>Part Number</dt>
                <dd className="mono">{response.part_number}</dd>
              </div>
              <div>
                <dt>Lot status</dt>
                {/* The backend's own status word, shown verbatim (rule 10). Not a verdict. */}
                <dd className="mono">
                  <span className="status-tag">{response.status}</span>
                </dd>
              </div>
              <div>
                <dt>Readings</dt>
                <dd className="mono">{response.reading_count}</dd>
              </div>
            </dl>
            {missing.length > 0 && (
              <p className="result-note">
                {missing.length} {missing.length === 1 ? 'component has' : 'components have'} no 0h
                or 24h reading for some parameter, so no forecast can be made for them:{' '}
                <span className="mono scroll-list">{missing.join(', ')}</span>
              </p>
            )}
          </div>
        )
      })}
      <Link className="button button-secondary result-link" to={pathToLot(last.lot_id)}>
        Open Lot Dashboard for {last.lot_id}
      </Link>
    </section>
  )
}

/**
 * E6 screen 2 / E7: a new lot's CSV with its metadata form, a later checkpoint CSV merged into a
 * lot on record, and the synthetic demo lot. Every call carries the signed-in account (E7 step
 * 11). Commit Batch sends whatever is staged: the lot first, then the checkpoint, and it stops at
 * the first failure so a checkpoint never targets a lot that didn't get created.
 */
export function IngestScreen() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const { session } = useAuth()
  const { rememberLot } = useWorkingLot()

  const [metadata, setMetadata] = useState<LotMetadata>(EMPTY_METADATA)
  const [lotFile, setLotFile] = useState<File | null>(null)
  const [checkpointFile, setCheckpointFile] = useState<File | null>(null)
  const [fileErrors, setFileErrors] = useState<{ lot?: string; checkpoint?: string }>({})
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<Field, string>>>({})
  const [batchError, setBatchError] = useState<{ title: string; lines: string[] } | null>(null)
  const [outcomes, setOutcomes] = useState<Outcome[]>([])
  const [busy, setBusy] = useState<'commit' | 'demo' | null>(null)
  const [dragging, setDragging] = useState(false)
  /** Text for the always-mounted status region, so screen readers hear each outcome. */
  const [announcement, setAnnouncement] = useState('')
  const inFlight = useRef(false)

  // A file dropped anywhere but the drop zone would make the browser open it, navigating away
  // and taking the in-memory session (rule 13) and everything staged with it.
  useEffect(() => {
    function block(event: Event) {
      event.preventDefault()
      if (event.type === 'drop') setDragging(false)
    }
    window.addEventListener('dragover', block)
    window.addEventListener('drop', block)
    return () => {
      window.removeEventListener('dragover', block)
      window.removeEventListener('drop', block)
    }
  }, [])

  const uid = useId()
  const ids = {
    lotFile: `${uid}-lot-file`,
    checkpointFile: `${uid}-checkpoint-file`,
    field: (key: Field) => `${uid}-${key}`,
    fieldError: (key: Field) => `${uid}-${key}-error`,
  }
  const accountId = session?.accountId ?? ''
  const disabled = busy !== null

  /** Stage or unstage a file. Field errors reflect the previous staging, so they're cleared. */
  function stage(which: 'lot' | 'checkpoint', file: File | null) {
    if (which === 'lot') setLotFile(file)
    else setCheckpointFile(file)
    setFieldErrors({})
    setBatchError(null)
  }

  function pick(which: 'lot' | 'checkpoint', file: File) {
    const refused = refuseFile(file)
    setFileErrors((e) => ({ ...e, [which]: refused ?? undefined }))
    if (!refused) stage(which, file)
  }

  function onDrop(event: DragEvent) {
    event.preventDefault()
    event.stopPropagation()
    setDragging(false)
    if (disabled) return
    const files = event.dataTransfer.files
    if (!files || files.length === 0) return
    if (files.length > 1) {
      setFileErrors((e) => ({ ...e, lot: 'Drop one CSV file at a time.' }))
      return
    }
    pick('lot', files[0])
  }

  function onDragLeave(event: DragEvent) {
    // dragleave also fires when moving onto the zone's own children; only leaving it counts.
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false)
  }

  function setField(key: Field, value: string) {
    setMetadata((m) => ({ ...m, [key]: value }))
    if (fieldErrors[key]) setFieldErrors((e) => ({ ...e, [key]: undefined }))
  }

  function validate(): boolean {
    const errors: Partial<Record<Field, string>> = {}
    const lotId = metadata.lot_id.trim()
    if (lotFile) {
      for (const { key } of FIELDS) {
        if (metadata[key].trim() === '') errors[key] = 'Required for a new lot.'
      }
      if (!errors.test_date && !isValidDate(metadata.test_date.trim())) {
        errors.test_date = 'Enter a real date (yyyy-mm-dd).'
      }
    } else if (checkpointFile && lotId === '') {
      errors.lot_id = 'Required: the checkpoint merges into this lot.'
    }
    if (lotId !== '' && !errors.lot_id) {
      const problem = lotIdProblem(lotId)
      if (problem) errors.lot_id = problem
    }
    setFieldErrors(errors)
    return Object.keys(errors).length === 0
  }

  async function run(kind: 'commit' | 'demo', steps: () => Promise<void>) {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(kind)
    setBatchError(null)
    setOutcomes([])
    setAnnouncement('')
    try {
      await steps()
    } finally {
      inFlight.current = false
      setBusy(null)
      void queryClient.invalidateQueries({ queryKey: PROJECTS_QUERY_KEY })
    }
  }

  function record(outcome: Outcome) {
    setOutcomes((o) => [...o, outcome])
    rememberLot(outcome.response.lot_id)
    const { lot_id, status } = outcome.response
    setAnnouncement((a) =>
      `${a} ${OUTCOME_LABEL[outcome.kind]}: ${lot_id}, status ${status}.`.trim(),
    )
  }

  function fail(title: string, error: unknown) {
    setBatchError({ title, lines: describeFailure(error) })
    setAnnouncement((a) => `${a} ${title}.`.trim())
  }

  async function commitBatch() {
    if (!session) return
    if (!lotFile && !checkpointFile) {
      setBatchError({
        title: 'Nothing to commit',
        lines: ['Choose a lot CSV or a checkpoint CSV first.'],
      })
      return
    }
    if (!validate()) return
    const trimmed = Object.fromEntries(
      Object.entries(metadata).map(([k, v]) => [k, v.trim()]),
    ) as unknown as LotMetadata

    await run('commit', async () => {
      if (lotFile) {
        try {
          await ensureReadable(lotFile)
          record({ kind: 'lot', response: await uploadLot(client, trimmed, lotFile, accountId) })
          setLotFile(null)
        } catch (error) {
          fail('Lot upload failed', error)
          return
        }
      }
      if (checkpointFile) {
        try {
          await ensureReadable(checkpointFile)
          const response = await uploadCheckpoint(client, trimmed.lot_id, checkpointFile, accountId)
          record({ kind: 'checkpoint', response })
          setCheckpointFile(null)
        } catch (error) {
          fail('Checkpoint upload failed', error)
        }
      }
    })
  }

  async function loadDemo() {
    if (!session) return
    await run('demo', async () => {
      try {
        record({ kind: 'demo', response: await loadDemoLot(client, accountId) })
      } catch (error) {
        fail('Demo lot failed to load', error)
      }
    })
  }

  return (
    <section className="screen ingest">
      <header className="screen-header">
        <div>
          <h1 className="screen-title">Ingest</h1>
          <p className="screen-subtitle">
            Accelerated life testing dataset upload and metadata binding
          </p>
        </div>
        <div className="screen-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={loadDemo}
            disabled={disabled}
          >
            <TerminalIcon />
            {busy === 'demo' ? 'Loading demo…' : 'Load Demo Lot'}
          </button>
          <button
            type="button"
            className="button button-primary"
            onClick={commitBatch}
            disabled={disabled}
          >
            <CloudUploadIcon />
            {busy === 'commit' ? 'Committing…' : 'Commit Batch'}
          </button>
        </div>
      </header>

      <p className="visually-hidden" role="status" data-testid="ingest-status">
        {announcement}
      </p>

      {batchError && (
        <div className="banner form-error" role="alert">
          <p className="banner-title">{batchError.title}</p>
          <MessageList lines={batchError.lines} />
        </div>
      )}

      {outcomes.length > 0 && <ResultPanel outcomes={outcomes} />}

      <div className="ingest-grid">
        <div className="ingest-column">
          <Card title="Upload Lot CSV" aside="Format: .csv only">
            <label
              htmlFor={ids.lotFile}
              className={`dropzone${dragging ? ' is-dragging' : ''}${disabled ? ' is-disabled' : ''}`}
              onDragOver={(e) => {
                e.preventDefault()
                if (!disabled) setDragging(true)
              }}
              onDragLeave={onDragLeave}
              onDrop={onDrop}
            >
              <span className="dropzone-icon">
                <FileUploadIcon />
              </span>
              <span className="dropzone-title">Drag and drop CSV lot file or browse</span>
              <span className="dropzone-hint">
                Iddq (standby current), leakage current, and propagation delay readings.
              </span>
            </label>
            <FileInput
              id={ids.lotFile}
              label="Lot CSV file"
              disabled={disabled}
              onPick={(file) => pick('lot', file)}
            />
            {lotFile && (
              <StagedFile file={lotFile} disabled={disabled} onRemove={() => stage('lot', null)} />
            )}
            {fileErrors.lot && (
              <p className="field-error" role="alert">
                {fileErrors.lot}
              </p>
            )}
          </Card>

          <Card
            title="Add Checkpoint Reading"
            icon={<RefreshClockIcon />}
            aside="Incremental (24h / 96h / 168h)"
          >
            <div className="checkpoint-row">
              <HourglassIcon />
              <div className="checkpoint-text">
                <p className="checkpoint-title">Append intermediate checkpoint CSV</p>
                <p className="checkpoint-sub">
                  Merge slice to matching active Lot record (by Lot ID)
                </p>
              </div>
              <label
                htmlFor={ids.checkpointFile}
                className={`button button-chip${disabled ? ' is-disabled' : ''}`}
              >
                Select file
              </label>
              <FileInput
                id={ids.checkpointFile}
                label="Checkpoint CSV file"
                disabled={disabled}
                onPick={(file) => pick('checkpoint', file)}
              />
            </div>
            {checkpointFile && (
              <StagedFile
                file={checkpointFile}
                disabled={disabled}
                onRemove={() => stage('checkpoint', null)}
              />
            )}
            {fileErrors.checkpoint && (
              <p className="field-error" role="alert">
                {fileErrors.checkpoint}
              </p>
            )}
          </Card>

          <Card title="Lot Metadata" aside="Required parameters">
            <div className="metadata-grid">
              {FIELDS.map(({ key, label, placeholder, type }) => {
                const error = fieldErrors[key]
                return (
                  <div className={`field${key === 'test_date' ? ' field-wide' : ''}`} key={key}>
                    <label className="field-label" htmlFor={ids.field(key)}>
                      {label}
                    </label>
                    <input
                      id={ids.field(key)}
                      className="input mono"
                      type={type ?? 'text'}
                      placeholder={placeholder}
                      value={metadata[key]}
                      onChange={(e) => setField(key, e.target.value)}
                      aria-invalid={!!error}
                      aria-describedby={error ? ids.fieldError(key) : undefined}
                      disabled={disabled}
                      autoComplete="off"
                      spellCheck={false}
                    />
                    {error && (
                      <p className="field-error" id={ids.fieldError(key)}>
                        {error}
                      </p>
                    )}
                  </div>
                )
              })}
            </div>
          </Card>
        </div>

        <RecentIngestions />
      </div>
    </section>
  )
}
