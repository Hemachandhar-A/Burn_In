import createClient from 'openapi-fetch'
import type { paths } from './schema'

/** Where `uvicorn api.main:app` listens in the two-process dev loop (Part 5.6). */
export const DEFAULT_API_BASE_URL = 'http://localhost:8000'

export interface ApiEnv {
  VITE_API_BASE_URL?: string
  DEV?: boolean
}

function invalid(raw: string, why: string): Error {
  return new Error(
    `VITE_API_BASE_URL is set to ${JSON.stringify(raw)}, which ${why}. Use an absolute ` +
      `http(s) URL such as http://localhost:8000, a path such as /api, or leave it empty for same-origin.`,
  )
}

/**
 * Where the backend lives:
 * - unset: the local uvicorn origin under `vite dev`; same-origin in a production build, since
 *   the demo build is served by FastAPI itself (Part 5.6's single-process shortcut)
 * - empty, or a path like `/api`: same-origin (under that path)
 * - an absolute http(s) URL: exactly that
 * Anything else throws, rather than silently turning into a relative path that 404s.
 */
export function resolveApiBaseUrl(
  env: ApiEnv = import.meta.env,
  origin: string = globalThis.location?.origin ?? '',
): string {
  const raw = env.VITE_API_BASE_URL
  if (raw === undefined) return env.DEV ? DEFAULT_API_BASE_URL : origin

  const value = raw.trim()
  if (/[?#]/.test(value)) throw invalid(raw, 'has a query string or fragment')
  if (value === '') return origin
  if (value.startsWith('/')) {
    if (value.startsWith('//')) throw invalid(raw, 'is protocol-relative')
    return origin + value.replace(/\/+$/, '')
  }

  let url: URL
  try {
    url = new URL(value)
  } catch {
    throw invalid(raw, 'is not a URL')
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw invalid(raw, 'is not an http(s) URL (a missing "http://" looks like this too)')
  }
  if (url.username || url.password) {
    throw invalid(raw, 'contains credentials, which the browser refuses to send in a request URL')
  }
  // Rebuilt from the parsed URL, so the client gets its normalized form, not the raw spelling.
  return url.origin + url.pathname.replace(/\/+$/, '')
}

interface ApiClientOptions {
  baseUrl: string
  /** Read on every request, so the client always sends whatever AuthContext holds right now. */
  getToken: () => string | null
  /** Called with the exact token a request carried when the server answered 401 with it. */
  onUnauthorized?: (rejectedToken: string) => void
  /** Injectable for tests; defaults to the global fetch. */
  fetch?: (input: Request) => Promise<Response>
}

const BEARER = /^Bearer (.+)$/

/**
 * The only way the frontend talks to the backend (AGENTS.md rule 14): typed end to end from
 * the generated `paths`, so a route or field the schema doesn't have is a compile error.
 */
export function createApiClient({ baseUrl, getToken, onUnauthorized, fetch }: ApiClientOptions) {
  const client = createClient<paths>({ baseUrl, ...(fetch && { fetch }) })
  client.use({
    onRequest({ request }) {
      const token = getToken()
      if (token) request.headers.set('Authorization', `Bearer ${token}`)
      return request
    },
    onResponse({ request, response }) {
      if (response.status !== 401 || !onUnauthorized) return undefined
      // The token this request actually sent - not whatever is current by the time it answers.
      const sent = BEARER.exec(request.headers.get('Authorization') ?? '')?.[1]
      if (sent) onUnauthorized(sent)
      return undefined
    },
  })
  return client
}

export type ApiClient = ReturnType<typeof createApiClient>
