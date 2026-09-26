import type { ApiClient } from './client'
import { ApiError, errorMessages } from './errors'
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

function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data !== undefined && result.response.ok) return result.data
  throw new ApiError(result.response.status, errorMessages(result.error, result.response.status))
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

/** `GET /projects`: every project on record (E11), newest first. */
export async function listProjects(client: ApiClient): Promise<ProjectSummary[]> {
  const projects = unwrap(await client.GET('/projects'))
  return [...projects].sort((a, b) => b.created_at.localeCompare(a.created_at))
}
