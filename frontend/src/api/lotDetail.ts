import type { ApiClient } from './client'
import { ApiError, errorMessages, unwrap } from './errors'
import type { components } from './schema'

export type LotSummaryResponse = components['schemas']['LotSummaryResponse']
export type DPAWorkOrderResponse = components['schemas']['DPAWorkOrderResponse']

/** `GET /lots/{lot_id}`: real (P5.3/5.6, fusion/router.py). */
export async function getLotSummary(
  client: ApiClient,
  lotId: string,
): Promise<LotSummaryResponse> {
  return unwrap(await client.GET('/lots/{lot_id}', { params: { path: { lot_id: lotId } } }))
}

/**
 * `POST /lots/{lot_id}/dpa-work-order`: real (Block 4a, capa/router.py). 409 when the lot is
 * still IN_PROGRESS (a DPA work order needs a final verdict tier to select against) - surfaces
 * through `unwrap` as an `ApiError` carrying the server's own message, same as any other route.
 */
export async function generateDpaWorkOrder(
  client: ApiClient,
  lotId: string,
): Promise<DPAWorkOrderResponse> {
  return unwrap(
    await client.POST('/lots/{lot_id}/dpa-work-order', { params: { path: { lot_id: lotId } } }),
  )
}

/**
 * `POST /lots/{lot_id}/report`: real (report/router.py, P2). Binary PDF by default, via the
 * generated client with `parseAs: 'blob'` - the schema types this route's body as
 * `application/json: unknown` because openapi-typescript can't express content-negotiated binary
 * responses, but the call still goes through the one generated client (rule 14), not a raw fetch.
 */
export async function downloadReport(
  client: ApiClient,
  lotId: string,
): Promise<{ blob: Blob; filename: string }> {
  const result = await client.POST('/lots/{lot_id}/report', {
    params: { path: { lot_id: lotId } },
    parseAs: 'blob',
  })
  if (!result.response.ok) {
    const raw = result.error as unknown
    const text = raw instanceof Blob ? await raw.text() : ''
    let body: unknown
    try {
      body = text ? JSON.parse(text) : undefined
    } catch {
      body = undefined
    }
    throw new ApiError(result.response.status, errorMessages(body, result.response.status))
  }
  const disposition = result.response.headers.get('content-disposition') ?? ''
  const match = /filename="?([^"]+)"?/.exec(disposition)
  return { blob: result.data as Blob, filename: match?.[1] ?? `${lotId}-report.pdf` }
}
