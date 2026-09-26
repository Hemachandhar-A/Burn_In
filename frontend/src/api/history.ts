import {
  MOCK_listDispositionSignoffs,
  MOCK_listEvents,
  type MOCK_DispositionRecord,
  type MOCK_EventResponse,
} from './mocks'

/** react-query key for `GET /events`; invalidate after anything that logs an event. */
export const EVENTS_QUERY_KEY = ['events'] as const
export const SIGNOFFS_QUERY_KEY = ['disposition-signoffs'] as const

/**
 * `GET /events`. MOCKED: not in the live OpenAPI schema. The Lead approved it on 2026-09-26
 * (CONTRACT_CHANGES.md, "P2.8's storage routes differ from Part 5.6") but P2 hasn't built it yet;
 * only the per-project `GET /projects/{project_id}/events` is live (BLOCKERS.md). When it lands,
 * take the ApiClient and call `client.GET('/events')`, as `listProjects` in lots.ts does.
 */
export function listEvents(): Promise<MOCK_EventResponse[]> {
  return MOCK_listEvents()
}

/** `GET /disposition-signoffs`. MOCKED, same status as `GET /events` above. */
export function listDispositionSignoffs(): Promise<MOCK_DispositionRecord[]> {
  return MOCK_listDispositionSignoffs()
}
