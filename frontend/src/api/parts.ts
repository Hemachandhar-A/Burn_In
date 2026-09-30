import type { ApiClient } from './client'
import { unwrap } from './errors'
import {
  MOCK_submitConfirmedOutcome,
  MOCK_submitDisposition,
  type MOCK_ConfirmedOutcomeRecord,
  type MOCK_ConfirmedOutcomeRequest,
  type MOCK_DispositionRecord,
  type MOCK_DispositionRequest,
} from './mocks'
import type { components } from './schema'

export type PartDetailResponse = components['schemas']['PartDetailResponse']

/**
 * `GET /parts/{component_id}`: real (P5.7, fusion/router.py). `lotId` is the route's own
 * documented optional query parameter, narrowing an ambiguous component_id (reused across lots)
 * to its most recent run within that one lot; omitted, the route resolves the newest run across
 * every lot that ever had this component_id.
 */
export async function getPartDetail(
  client: ApiClient,
  componentId: string,
  lotId?: string,
): Promise<PartDetailResponse> {
  return unwrap(
    await client.GET('/parts/{component_id}', {
      params: { path: { component_id: componentId }, query: { lot_id: lotId } },
    }),
  )
}

/**
 * `POST /parts/{component_id}/disposition`. MOCKED: the real route needs `project_id` and
 * `analysis_run_id` as required query parameters, and `PartDetailResponse` gives the frontend no
 * way to obtain either (CONTRACT_CHANGES.md, "PartDetailResponse gives the frontend no way to
 * call POST /parts/{component_id}/disposition correctly").
 */
export function submitDisposition(
  componentId: string,
  request: MOCK_DispositionRequest,
  accountId: string,
): Promise<MOCK_DispositionRecord> {
  return MOCK_submitDisposition(componentId, request, accountId)
}

/** `POST /parts/{component_id}/confirmed-outcome`. MOCKED: blocked on Block 4a merge. */
export function submitConfirmedOutcome(
  componentId: string,
  request: MOCK_ConfirmedOutcomeRequest,
  accountId: string,
): Promise<MOCK_ConfirmedOutcomeRecord> {
  return MOCK_submitConfirmedOutcome(componentId, request, accountId)
}
