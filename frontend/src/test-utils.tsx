/**
 * Test-only: render a screen against the real generated client, with fetch answered by a fake
 * server. Screens go through the same request code as in the app, and a test decides only what
 * the backend says back.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import { ApiClientContext } from './api/ApiClientContext'
import { createApiClient } from './api/client'
import type { Session } from './auth/AuthContext'
import { AuthProvider } from './auth/AuthProvider'

export const TEST_API = 'http://api.test'

export interface FakeReply {
  status?: number
  body: unknown
}

/** `'POST /lots'` -> reply, or a function of the request. Unlisted routes answer 404. */
export type Routes = Record<
  string,
  FakeReply | ((request: Request) => FakeReply | Promise<FakeReply>)
>

export function fakeServer(routes: Routes) {
  const requests: Request[] = []
  const fetch = vi.fn(async (request: Request) => {
    requests.push(request)
    const key = `${request.method} ${new URL(request.url).pathname}`
    const route = routes[key]
    const reply = typeof route === 'function' ? await route(request) : route
    const { status = 200, body } = reply ?? { status: 404, body: { detail: `no fake for ${key}` } }
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  return { fetch, requests }
}

export const SIGNED_IN: Session = {
  token: 'jwt-test',
  accountId: 'a.sharma',
  role: 'Quality Engineer',
}

export function renderWithApi(
  ui: ReactNode,
  {
    fetch,
    session = SIGNED_IN,
    path = '/',
  }: { fetch: (r: Request) => Promise<Response>; session?: Session | null; path?: string },
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const client = createApiClient({
    baseUrl: TEST_API,
    getToken: () => session?.token ?? null,
    fetch,
  })
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider initialSession={session}>
          <ApiClientContext.Provider value={client}>
            <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
          </ApiClientContext.Provider>
        </AuthProvider>
      </QueryClientProvider>,
    ),
  }
}
