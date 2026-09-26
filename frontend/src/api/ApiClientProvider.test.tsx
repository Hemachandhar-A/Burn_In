import { act, render, screen } from '@testing-library/react'
import { describe, expect, test, vi } from 'vitest'
import { useAuth, type AuthState, type TokenResponse } from '../auth/AuthContext'
import { AuthProvider } from '../auth/AuthProvider'
import { useApiClient } from './ApiClientContext'
import { ApiClientProvider } from './ApiClientProvider'
import type { ApiClient } from './client'

const TOKEN: TokenResponse = {
  access_token: 'jwt-abc',
  token_type: 'bearer',
  account_id: 'asharma',
  role: 'Quality Engineer',
}
const ENV = { VITE_API_BASE_URL: 'http://api.test', DEV: true }

function jsonFetch(status = 200) {
  const requests: Request[] = []
  const fetch = vi.fn(async (input: Request) => {
    requests.push(input)
    return new Response('{"status":"ok"}', {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  return { fetch, requests }
}

/** Captures the client and auth state the tree actually sees, render by render. */
function mount(fetch: (input: Request) => Promise<Response>, env = ENV) {
  const seen: { clients: ApiClient[]; auth: AuthState | null } = { clients: [], auth: null }
  function Probe() {
    seen.clients.push(useApiClient())
    seen.auth = useAuth()
    return <p>ready</p>
  }
  render(
    <AuthProvider>
      <ApiClientProvider env={env} fetch={fetch}>
        <Probe />
      </ApiClientProvider>
    </AuthProvider>,
  )
  return seen
}

describe('ApiClientProvider', () => {
  test('useApiClient outside the provider fails loudly', () => {
    function Orphan() {
      useApiClient()
      return null
    }
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<Orphan />)).toThrow(/ApiClientProvider/)
    quiet.mockRestore()
  })

  test('keeps one client across sign-in and sign-out; requests carry the current token', async () => {
    const { fetch, requests } = jsonFetch()
    const seen = mount(fetch)
    const first = seen.clients[0]

    await first.GET('/health')
    act(() => seen.auth!.signIn(TOKEN))
    await first.GET('/health') // a client captured before sign-in still sends the new token
    act(() => seen.auth!.signOut())
    await first.GET('/health')

    expect(new Set(seen.clients).size).toBe(1)
    expect(requests.map((r) => r.headers.get('Authorization'))).toEqual([
      null,
      'Bearer jwt-abc',
      null,
    ])
    expect(requests[0].url).toBe('http://api.test/health')
  })

  test('a 401 on an authenticated request signs the account out', async () => {
    const { fetch } = jsonFetch(401)
    const seen = mount(fetch)
    act(() => seen.auth!.signIn(TOKEN))

    await act(async () => {
      await seen.clients.at(-1)!.GET('/health')
    })

    expect(seen.auth!.session).toBeNull()
  })

  test('a misconfigured VITE_API_BASE_URL shows a visible error instead of a blank page', () => {
    const { fetch } = jsonFetch()
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <AuthProvider>
        <ApiClientProvider env={{ VITE_API_BASE_URL: 'localhost:8000', DEV: true }} fetch={fetch}>
          <p>app</p>
        </ApiClientProvider>
      </AuthProvider>,
    )
    quiet.mockRestore()

    expect(screen.getByRole('alert')).toHaveTextContent(/VITE_API_BASE_URL/)
    expect(screen.getByRole('alert')).toHaveTextContent(/localhost:8000/)
    expect(screen.queryByText('app')).toBeNull()
  })
})
