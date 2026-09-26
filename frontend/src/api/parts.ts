import {
  MOCK_getPartDetail,
  MOCK_submitConfirmedOutcome,
  MOCK_submitDisposition,
  type MOCK_ConfirmedOutcomeRecord,
  type MOCK_ConfirmedOutcomeRequest,
  type MOCK_DispositionRecord,
  type MOCK_DispositionRequest,
  type TEMP_PartDetailResponse,
} from './mocks'

/**
 * `GET /parts/{component_id}`. MOCKED: not in the live OpenAPI schema (P5.7, BLOCKERS.md). `hint`
 * carries context passed from the Lot Dashboard (the lot id, fused verdict and worst parameter
 * already shown there) so opening a part from its ranked list is consistent with the row just
 * clicked; a direct deep link to `/parts/:componentId` has no hint and the mock derives
 * everything from the id alone.
 */
export function getPartDetail(
  componentId: string,
  hint?: { lotId?: string; verdict?: 'PASS' | 'WATCH' | 'REJECT'; worstParameter?: string },
): Promise<TEMP_PartDetailResponse> {
  return MOCK_getPartDetail(componentId, hint)
}

/** `POST /parts/{component_id}/disposition`. MOCKED (P5.5, BLOCKERS.md). */
export function submitDisposition(
  componentId: string,
  request: MOCK_DispositionRequest,
  accountId: string,
): Promise<MOCK_DispositionRecord> {
  return MOCK_submitDisposition(componentId, request, accountId)
}

/** `POST /parts/{component_id}/confirmed-outcome`. MOCKED (P5.8, BLOCKERS.md). */
export function submitConfirmedOutcome(
  componentId: string,
  request: MOCK_ConfirmedOutcomeRequest,
  accountId: string,
): Promise<MOCK_ConfirmedOutcomeRecord> {
  return MOCK_submitConfirmedOutcome(componentId, request, accountId)
}
