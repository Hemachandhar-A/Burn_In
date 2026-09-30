/**
 * There are no mocked routes left: every route a screen calls is real (Block 5D swapped the last,
 * `POST /parts/{component_id}/disposition`). What remains is fixture data only.
 */

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
