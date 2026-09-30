import type { Location } from 'react-router-dom'
import { screenById } from '../screens/registry'

/** What RequireAuth hands Login in router state: the page it bounced away from. */
export interface ReturnState {
  from?: Pick<Location, 'pathname' | 'search' | 'hash'>
}

/**
 * Where to go once signed in: the page RequireAuth bounced away from (query and hash intact),
 * else `fallback`. Anything that isn't an in-app path - or is Login itself - falls back.
 */
export function returnTarget(state: unknown, fallback: string): string {
  const from = (state as ReturnState | null)?.from
  if (!from || typeof from.pathname !== 'string') return fallback
  const { pathname } = from
  if (!pathname.startsWith('/') || pathname.startsWith('//')) return fallback
  if (pathname.replace(/\/+$/, '') === screenById('login').path) return fallback
  const search = typeof from.search === 'string' ? from.search : ''
  const hash = typeof from.hash === 'string' ? from.hash : ''
  return pathname + search + hash
}
