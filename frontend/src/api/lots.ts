import type { ApiClient } from './client'
import { ApiError, unwrap } from './errors'
import type { components } from './schema'

export type LotUploadResponse = components['schemas']['LotUploadResponse']
export type ProjectSummary = components['schemas']['ProjectSummary']
type UploadLotBody = components['schemas']['Body_upload_lot_lots_post']
type UploadCheckpointBody =
  components['schemas']['Body_upload_checkpoint_lots__lot_id__checkpoints_post']

/** The ingestion metadata form (E7 step 1). Lot-level metadata comes from here, never CSV columns. */
export interface LotMetadata {
  lot_id: string
  part_number: string
  manufacturer: string
  date_code: string
  /** yyyy-mm-dd, as an <input type="date"> gives it. */
  test_date: string
}

/**
 * openapi-typescript renders an `UploadFile` field as `string` (the schema says type: string).
 * What actually goes on the wire is the file itself, in a multipart body, so this one cast bridges
 * the generated type to the runtime value. It doesn't loosen any other field.
 */
function uploadField(file: Blob): string {
  return file as unknown as string
}

/** Multipart body from a generated `Body_*` object; unset optional fields are left out. */
function toFormData(body: Record<string, unknown>): FormData {
  const form = new FormData()
  for (const [key, value] of Object.entries(body)) {
    if (value === undefined || value === null) continue
    if (value instanceof Blob) form.append(key, value, value instanceof File ? value.name : key)
    else form.append(key, String(value))
  }
  return form
}

/**
 * `POST /lots`: a new lot's first CSV plus its metadata. `accountId` is a form field today because
 * the route has no auth dependency until identity/ lands (ingestion/router.py docstring). When it
 * does, the schema drops the field and this stops compiling, which is the point.
 */
export async function uploadLot(
  client: ApiClient,
  metadata: LotMetadata,
  file: File,
  accountId: string,
): Promise<LotUploadResponse> {
  const body: UploadLotBody = { ...metadata, account_id: accountId, file: uploadField(file) }
  return unwrap(await client.POST('/lots', { body, bodySerializer: toFormData }))
}

/** `POST /lots/{lot_id}/checkpoints`: merges a later checkpoint CSV into a lot already on record (E7 step 3). */
export async function uploadCheckpoint(
  client: ApiClient,
  lotId: string,
  file: File,
  accountId: string,
): Promise<LotUploadResponse> {
  const body: UploadCheckpointBody = { account_id: accountId, file: uploadField(file) }
  return unwrap(
    await client.POST('/lots/{lot_id}/checkpoints', {
      params: { path: { lot_id: lotId } },
      body,
      bodySerializer: toFormData,
    }),
  )
}

/** `POST /lots/demo`: the synthetic demo lot (E7 step 2). The schema declares a urlencoded form body. */
export async function loadDemoLot(
  client: ApiClient,
  accountId: string,
): Promise<LotUploadResponse> {
  return unwrap(
    await client.POST('/lots/demo', {
      body: { account_id: accountId },
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    }),
  )
}

/** react-query cache key for `GET /projects`; invalidate it after anything that creates a lot. */
export const PROJECTS_QUERY_KEY = ['projects'] as const

/** `GET /projects`: every project on record (E11), newest first. Ties keep server order. */
export async function listProjects(client: ApiClient): Promise<ProjectSummary[]> {
  const projects = unwrap(await client.GET('/projects'))
  // Plain string order, not localeCompare: ISO timestamps sort correctly as code points, and
  // this can't vary with the browser's locale.
  return [...projects].sort((a, b) =>
    a.created_at === b.created_at ? 0 : a.created_at < b.created_at ? 1 : -1,
  )
}

/**
 * `GET /projects/{project_id}`: one project's metadata (`ProjectSummary`). `project_id` equals
 * `lot_id` for every lot the ingestion routes create (ingestion/router.py saves the project and
 * its events with `project_id=dataset.lot_id`), so the Lot Dashboard passes its lot id.
 */
export async function getProject(client: ApiClient, projectId: string): Promise<ProjectSummary> {
  return unwrap(
    await client.GET('/projects/{project_id}', { params: { path: { project_id: projectId } } }),
  )
}

/**
 * Why a lot id can't be used, or null. Every later call addresses a lot by URL path
 * (`/lots/{lot_id}/...`). Starlette decodes `%2F` back to `/` before routing, and browsers
 * collapse `.`/`..` path segments, so such a lot could be created and then never reached again
 * (checked against the running backend: create 200, checkpoint 404).
 */
export function lotIdProblem(lotId: string): string | null {
  if (lotId.includes('/')) return "Lot ID can't contain “/”: lots are addressed by URL path."
  if (/^\.+$/.test(lotId)) return "Lot ID can't be only dots: lots are addressed by URL path."
  return null
}

/**
 * Throws a readable ApiError if a staged file can no longer be read. Browsers snapshot a chosen
 * file, and one edited or deleted on disk since then fails to upload with a generic network
 * error. Reading one byte first names the actual cause.
 */
export async function ensureReadable(file: File): Promise<void> {
  try {
    await file.slice(0, 1).arrayBuffer()
  } catch {
    throw new ApiError(0, [
      `${file.name} changed or was removed after you chose it. Choose it again.`,
    ])
  }
}
