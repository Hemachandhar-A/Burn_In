import createClient from 'openapi-fetch'
import type { paths } from './schema'

/** Where `uvicorn api.main:app` listens in the two-process dev loop (Part 5.6). */
export const DEFAULT_API_BASE_URL = 'http://localhost:8000'

/**
 * VITE_API_BASE_URL unset -> the local uvicorn origin. Set to an empty string -> same-origin,
 * for the single-process demo build where FastAPI serves the built frontend itself.
 */
export function resolveApiBaseUrl(env: { VITE_API_BASE_URL?: string } = import.meta.env): string {
  return (env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL).replace(/\/+$/, '')
}

interface ApiClientOptions {
  baseUrl: string
  /** Read on every request, so the client always sends whatever AuthContext holds right now. */
  getToken: () => string | null
  /** Injectable for tests; defaults to the global fetch. */
  fetch?: (input: Request) => Promise<Response>
}

/**
 * The only way the frontend talks to the backend (AGENTS.md rule 14): typed end to end from
 * the generated `paths`, so a route or field the schema doesn't have is a compile error.
 */
export function createApiClient({ baseUrl, getToken, fetch }: ApiClientOptions) {
  const client = createClient<paths>({ baseUrl, ...(fetch && { fetch }) })
  client.use({
    onRequest({ request }) {
      const token = getToken()
      if (token) request.headers.set('Authorization', `Bearer ${token}`)
      return request
    },
  })
  return client
}

export type ApiClient = ReturnType<typeof createApiClient>
