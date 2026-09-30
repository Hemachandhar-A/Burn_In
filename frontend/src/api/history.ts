import type { ApiClient } from './client'
import { unwrap } from './errors'
import type { components } from './schema'

export type EventResponse = components['schemas']['EventResponse']
export type DispositionRecord = components['schemas']['DispositionRecord']

/** react-query key for `GET /events`; invalidate after anything that logs an event. */
export const EVENTS_QUERY_KEY = ['events'] as const
export const SIGNOFFS_QUERY_KEY = ['disposition-signoffs'] as const

/** `GET /events`: real (P2.8, storage/router.py). Every event, every project, every account. */
export async function listEvents(client: ApiClient): Promise<EventResponse[]> {
  return unwrap(await client.GET('/events'))
}

/** `GET /disposition-signoffs`: real (P2.8, storage/router.py). */
export async function listDispositionSignoffs(client: ApiClient): Promise<DispositionRecord[]> {
  return unwrap(await client.GET('/disposition-signoffs'))
}
