import type { ApiClient } from './client'
import { unwrap } from './errors'
import type { components } from './schema'

export type PartDetailResponse = components['schemas']['PartDetailResponse']
export type DispositionRequest = components['schemas']['DispositionRequest']
export type DispositionRecord = components['schemas']['DispositionRecord']
export type ConfirmedOutcomeRequest = components['schemas']['ConfirmedOutcomeRequest']
export type ConfirmedOutcomeRecord = components['schemas']['ConfirmedOutcomeRecord']

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
 * `POST /parts/{component_id}/disposition`: real (P5.5, identity/router.py). The route takes
 * `project_id` and `analysis_run_id` as required query parameters; `PartDetailResponse` now
 * returns both (Block 4c Part 3a), so the caller passes them straight from the fetched part.
 */
export async function submitDisposition(
  client: ApiClient,
  componentId: string,
  ids: { projectId: string; analysisRunId: string },
  request: DispositionRequest,
): Promise<DispositionRecord> {
  return unwrap(
    await client.POST('/parts/{component_id}/disposition', {
      params: {
        path: { component_id: componentId },
        query: { project_id: ids.projectId, analysis_run_id: ids.analysisRunId },
      },
      body: request,
    }),
  )
}

/**
 * `POST /parts/{component_id}/confirmed-outcome`: real (Block 4a, capa/router.py). Unlike
 * disposition, the route resolves its own `project_id`/`analysis_run_id` server-side (keyed by
 * `component_id` and the optional `lotId` query parameter), so no missing-parameter blocker here.
 */
export async function submitConfirmedOutcome(
  client: ApiClient,
  componentId: string,
  request: ConfirmedOutcomeRequest,
  lotId?: string,
): Promise<ConfirmedOutcomeRecord> {
  return unwrap(
    await client.POST('/parts/{component_id}/confirmed-outcome', {
      params: { path: { component_id: componentId }, query: { lot_id: lotId } },
      body: request,
    }),
  )
}
