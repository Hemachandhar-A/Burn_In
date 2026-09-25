import { QueryClient } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test } from 'vitest'
import App from './App'
import { AppProviders } from './AppProviders'
import { useAuth, type Session, type TEMP_TokenResponse } from './auth/AuthContext'
import { SCREENS } from './screens/registry'

const SESSION: Session = { token: 'jwt-abc', accountId: 'asharma', role: 'Quality Engineer' }
const OTHER: TEMP_TokenResponse = {
  access_token: 'jwt-xyz',
  token_type: 'bearer',
  account_id: 'rmehta',
  role: 'Reliability Engineer',
}

beforeEach(() => window.history.replaceState(null, '', '/'))
afterEach(() => window.history.replaceState(null, '', '/'))

describe('App', () => {
  test('a fresh load starts at Login (rule 13: a hard refresh re-prompts)', () => {
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: 'Login' })).toBeInTheDocument()
  })

  test('a fresh load of a deep screen URL also lands on Login', () => {
    window.history.replaceState(null, '', '/#/lots/LOT-001')
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: 'Login' })).toBeInTheDocument()
  })

  test('screens live in the URL hash, so the server only ever serves "/"', () => {
    window.history.replaceState(null, '', '/#/settings')
    render(<App />)

    expect(window.location.pathname).toBe('/')
    expect(window.location.hash).toBe('#/login')
  })

  test('why hash routing: screen paths share names with API routes (Part 5.6 same-origin build)', () => {
    // If the router used real paths, refreshing /settings or /lots/X in the single-process demo
    // build would hit these FastAPI routes and show JSON instead of the app. This documents the
    // overlap so nobody "simplifies" back to BrowserRouter without seeing why.
    const plannedApiPrefixes = ['/lots', '/parts', '/projects', '/settings']
    const screenPrefixes = SCREENS.map((s) => '/' + s.path.split('/')[1])
    expect(plannedApiPrefixes.filter((p) => screenPrefixes.includes(p))).toEqual(plannedApiPrefixes)
  })
})

describe('AppProviders: cached server data never outlives its session', () => {
  function seeded() {
    const queryClient = new QueryClient()
    queryClient.setQueryData(['lot', 'LOT-001'], { verdict: 'REJECT' })
    return queryClient
  }

  function Controls() {
    const auth = useAuth()
    return (
      <div>
        <button onClick={auth.signOut}>sign out</button>
        <button onClick={() => auth.signIn(OTHER)}>switch account</button>
        <button onClick={() => auth.handleUnauthorized(auth.session?.token ?? '')}>401</button>
      </div>
    )
  }

  test.each(['sign out', 'switch account', '401'])('%s clears the query cache', (action) => {
    const queryClient = seeded()
    render(
      <AppProviders queryClient={queryClient} initialSession={SESSION}>
        <Controls />
      </AppProviders>,
    )

    act(() => fireEvent.click(screen.getByRole('button', { name: action })))

    expect(queryClient.getQueryData(['lot', 'LOT-001'])).toBeUndefined()
  })

  test('the cache is left alone while the same session carries on', () => {
    const queryClient = seeded()
    render(
      <AppProviders queryClient={queryClient} initialSession={SESSION}>
        <Controls />
      </AppProviders>,
    )

    expect(queryClient.getQueryData(['lot', 'LOT-001'])).toEqual({ verdict: 'REJECT' })
  })
})
