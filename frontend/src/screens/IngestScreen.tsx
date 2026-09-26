import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useRef, useState, type DragEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useApiClient } from '../api/ApiClientContext'
import { describeFailure } from '../api/errors'
import {
  listProjects,
  loadDemoLot,
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
import { pathToLot } from './registry'

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

/** `2026-09-26T14:32:10.123` -> `2026-09-26 14:32`, as stored, with no timezone conversion. */
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
  const count = projects.data?.length

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
          {describeFailure(projects.error).map((line) => (
            <p key={line}>{line}</p>
          ))}
          <button
            type="button"
            className="button button-secondary"
            onClick={() => projects.refetch()}
          >
            Retry
          </button>
        </div>
      )}

      {projects.isSuccess && projects.data.length === 0 && (
        <p className="card-note">No lots on record yet.</p>
      )}

      {projects.isSuccess && projects.data.length > 0 && (
        <table className="table" aria-labelledby={headingId}>
          <thead>
            <tr>
              <th scope="col">Lot ID</th>
              <th scope="col">Part Number</th>
              <th scope="col" className="numeric">
                Uploaded
              </th>
            </tr>
          </thead>
          <tbody>
            {projects.data.map((p) => (
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
    </section>
  )
}

function ResultPanel({ outcomes }: { outcomes: Outcome[] }) {
  const last = outcomes[outcomes.length - 1].response
  return (
    <section className="card result" aria-label="Ingestion result" aria-live="polite">
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
                <span className="mono">{missing.join(', ')}</span>
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
  const inFlight = useRef(false)

  const uid = useId()
  const ids = {
    lotFile: `${uid}-lot-file`,
    checkpointFile: `${uid}-checkpoint-file`,
    field: (key: Field) => `${uid}-${key}`,
    fieldError: (key: Field) => `${uid}-${key}-error`,
  }
  const accountId = session?.accountId ?? ''
  const disabled = busy !== null

  function pick(which: 'lot' | 'checkpoint', file: File) {
    const refused = refuseFile(file)
    setFileErrors((e) => ({ ...e, [which]: refused ?? undefined }))
    if (refused) return
    if (which === 'lot') setLotFile(file)
    else setCheckpointFile(file)
    setBatchError(null)
  }

  function onDrop(event: DragEvent) {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files?.[0]
    if (file && !disabled) pick('lot', file)
  }

  function setField(key: Field, value: string) {
    setMetadata((m) => ({ ...m, [key]: value }))
    if (fieldErrors[key]) setFieldErrors((e) => ({ ...e, [key]: undefined }))
  }

  function validate(): boolean {
    const errors: Partial<Record<Field, string>> = {}
    if (lotFile) {
      for (const { key } of FIELDS) {
        if (metadata[key].trim() === '') errors[key] = 'Required for a new lot.'
      }
    } else if (checkpointFile && metadata.lot_id.trim() === '') {
      errors.lot_id = 'Required: the checkpoint merges into this lot.'
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
  }

  async function commitBatch() {
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
          record({ kind: 'lot', response: await uploadLot(client, trimmed, lotFile, accountId) })
          setLotFile(null)
        } catch (error) {
          setBatchError({ title: 'Lot upload failed', lines: describeFailure(error) })
          return
        }
      }
      if (checkpointFile) {
        try {
          const response = await uploadCheckpoint(client, trimmed.lot_id, checkpointFile, accountId)
          record({ kind: 'checkpoint', response })
          setCheckpointFile(null)
        } catch (error) {
          setBatchError({ title: 'Checkpoint upload failed', lines: describeFailure(error) })
        }
      }
    })
  }

  async function loadDemo() {
    await run('demo', async () => {
      try {
        record({ kind: 'demo', response: await loadDemoLot(client, accountId) })
      } catch (error) {
        setBatchError({ title: 'Demo lot failed to load', lines: describeFailure(error) })
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

      {batchError && (
        <div className="banner form-error" role="alert">
          <p className="banner-title">{batchError.title}</p>
          <ul>
            {batchError.lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
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
              onDragLeave={() => setDragging(false)}
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
              <StagedFile file={lotFile} disabled={disabled} onRemove={() => setLotFile(null)} />
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
                onRemove={() => setCheckpointFile(null)}
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
