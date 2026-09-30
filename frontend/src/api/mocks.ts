/**
 * Hand-typed stand-ins for routes not yet in the live OpenAPI schema. Each MOCK_<TypeName>
 * mirrors its contracts.py Pydantic model field for field, and each has an open BLOCKERS.md entry
 * naming the route it stands in for.
 *
 * When a route goes live, the one function that calls its mock is edited to call the generated
 * client, and the mock is deleted here. There is no global mock switch on purpose.
 *
 * As of Block 5C, every mocked route except `POST /parts/{component_id}/disposition` is real
 * (`GET /lots/{lot_id}`, `GET /parts/{component_id}`, `GET /settings/worklist`,
 * `GET /settings/corrective-status`, `POST /lots/{lot_id}/dpa-work-order`,
 * `POST /parts/{component_id}/confirmed-outcome`) - their `TEMP_`/`MOCK_` response types and
 * fixture generators were deleted in Block 5B-1/5B-2/5C. `POST /parts/{component_id}/disposition`
 * stays mocked: CONTRACT_CHANGES.md, "PartDetailResponse gives the frontend no way to call
 * POST /parts/{component_id}/disposition correctly" (needs `project_id`/`analysis_run_id` query
 * parameters the response gives the frontend no way to obtain). Block 5D swaps this.
 */
import { ApiError } from './errors'

/** contracts.py `DispositionRecord`, verbatim. */
export interface MOCK_DispositionRecord {
  project_id: string
  component_id: string
  account_id: string
  verdict: 'ACCEPT' | 'HOLD' | 'REJECT'
  rationale: string
  timestamp: string
  analysis_run_id: string
}

/** contracts.py `DispositionRequest`, verbatim. */
export interface MOCK_DispositionRequest {
  verdict: 'ACCEPT' | 'HOLD' | 'REJECT'
  rationale: string
}

const MOCK_LATENCY_SHORT_MS = 200

/** `POST /parts/{component_id}/disposition` (P5.5, identity/router.py). */
export async function MOCK_submitDisposition(
  componentId: string,
  request: MOCK_DispositionRequest,
  accountId: string,
): Promise<MOCK_DispositionRecord> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_SHORT_MS))
  if (request.rationale.trim() === '')
    throw new ApiError(422, ['A technical rationale is required.'])
  return {
    project_id: `proj-${componentId}`,
    component_id: componentId,
    account_id: accountId,
    verdict: request.verdict,
    rationale: request.rationale,
    timestamp: new Date().toISOString(),
    analysis_run_id: '03',
  }
}

/**
 * The projects a few screens' tests refer to, in contracts.py `ProjectSummary` shape. Not served
 * by any mock - `GET /projects` is real. Exported so tests can answer the real route with them,
 * and so a local database can be seeded with the same rows (via storage's `save_project`) when
 * screenshot-verifying.
 */
export const MOCK_FIXTURE_PROJECTS = [
  {
    project_id: 'proj-LOT-2024-6090',
    lot_id: 'LOT-2024-6090',
    part_number: 'OP27-AZ',
    created_by: 'a.sharma',
    created_at: '2026-09-09T08:10:00Z',
  },
  {
    project_id: 'proj-LOT-2024-7712',
    lot_id: 'LOT-2024-7712',
    part_number: 'LM117-HV',
    created_by: 'r.mehta',
    created_at: '2026-09-10T09:40:00Z',
  },
  {
    project_id: 'proj-LOT-2024-8841',
    lot_id: 'LOT-2024-8841',
    part_number: 'AD590-JH',
    created_by: 'r.mehta',
    created_at: '2026-09-11T09:15:30Z',
  },
  {
    project_id: 'proj-LOT-2024-9104',
    lot_id: 'LOT-2024-9104',
    part_number: 'AD590-JH',
    created_by: 'r.mehta',
    created_at: '2026-09-14T10:05:00Z',
  },
  {
    project_id: 'proj-LOT-2024-9230',
    lot_id: 'LOT-2024-9230',
    part_number: 'DAC8830',
    created_by: 'a.sharma',
    created_at: '2026-09-15T14:32:01Z',
  },
] as const
