import type { ApiClient } from './client'
import { ApiError, errorMessages } from './errors'
import {
  MOCK_generateDpaWorkOrder,
  MOCK_getLotSummary,
  type MOCK_DPAWorkOrderResponse,
  type TEMP_LotSummaryResponse,
} from './mocks'

/**
 * `GET /lots/{lot_id}`. MOCKED: not in the live OpenAPI schema (P5.3, BLOCKERS.md). When it
 * lands, regenerate the client and make this take the ApiClient and call
 * `client.GET('/lots/{lot_id}', { params: { path: { lot_id: lotId } } })`.
 */
export function getLotSummary(lotId: string): Promise<TEMP_LotSummaryResponse> {
  return MOCK_getLotSummary(lotId)
}

/**
 * `POST /lots/{lot_id}/dpa-work-order`. MOCKED: not in the live schema (P5.8, BLOCKERS.md).
 */
export function generateDpaWorkOrder(lotId: string): Promise<MOCK_DPAWorkOrderResponse> {
  return MOCK_generateDpaWorkOrder(lotId)
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
