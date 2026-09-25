import { act, render, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { useAuth, type TEMP_TokenResponse } from './AuthContext'
import { AuthProvider } from './AuthProvider'

const TOKEN: TEMP_TokenResponse = {
  access_token: 'jwt-abc',
  token_type: 'bearer',
  account_id: 'asharma',
  role: 'Quality Engineer',
}
const OTHER: TEMP_TokenResponse = {
  access_token: 'jwt-xyz',
  token_type: 'bearer',
  account_id: 'rmehta',
  role: 'Reliability Engineer',
}

function setup(onSessionEnd?: () => void) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <AuthProvider onSessionEnd={onSessionEnd}>{children}</AuthProvider>
  )
  return renderHook(() => useAuth(), { wrapper })
}

afterEach(() => {
  localStorage.clear()
  sessionStorage.clear()
})

describe('AuthProvider', () => {
  test('starts signed out', () => {
    const { result } = setup()
    expect(result.current.session).toBeNull()
    expect(result.current.getToken()).toBeNull()
  })

  test('signIn holds the token, account and role from the login response', () => {
    const { result } = setup()

    act(() => result.current.signIn(TOKEN))

    expect(result.current.session).toEqual({
      token: 'jwt-abc',
      accountId: 'asharma',
      role: 'Quality Engineer',
    })
    expect(result.current.getToken()).toBe('jwt-abc')
  })

  test('signOut discards the token', () => {
    const { result } = setup()

    act(() => result.current.signIn(TOKEN))
    act(() => result.current.signOut())

    expect(result.current.session).toBeNull()
    expect(result.current.getToken()).toBeNull()
  })

  test('signing in as another account replaces the session outright', () => {
    const { result } = setup()

    act(() => result.current.signIn(TOKEN))
    act(() => result.current.signIn(OTHER))

    expect(result.current.session).toEqual({
      token: 'jwt-xyz',
      accountId: 'rmehta',
      role: 'Reliability Engineer',
    })
  })

  test.each<[string, Partial<Record<keyof TEMP_TokenResponse, string>>]>([
    ['an empty token', { access_token: '' }],
    ['a whitespace token', { access_token: '   ' }],
    ['a non-bearer token type', { token_type: 'basic' }],
    ['an empty account id', { account_id: '' }],
  ])('signIn rejects %s and stays signed out', (_label, patch) => {
    const { result } = setup()
    const bad = { ...TOKEN, ...patch } as unknown as TEMP_TokenResponse

    expect(() => act(() => result.current.signIn(bad))).toThrow(/login response/)
    expect(result.current.session).toBeNull()
  })

  test('getToken is one stable function that always returns the current token', () => {
    const { result } = setup()
    const getToken = result.current.getToken

    act(() => result.current.signIn(TOKEN))
    expect(result.current.getToken).toBe(getToken)
    expect(getToken()).toBe('jwt-abc')

    act(() => result.current.signIn(OTHER))
    expect(getToken()).toBe('jwt-xyz')

    act(() => result.current.signOut())
    expect(result.current.getToken).toBe(getToken)
    expect(getToken()).toBeNull()
  })

  test('handleUnauthorized with the current token signs out (expired/tampered JWT)', () => {
    const { result } = setup()

    act(() => result.current.signIn(TOKEN))
    act(() => result.current.handleUnauthorized('jwt-abc'))

    expect(result.current.session).toBeNull()
  })

  test('a late 401 for a previous session does not sign out the newer one', () => {
    const { result } = setup()

    act(() => result.current.signIn(TOKEN))
    act(() => result.current.signIn(OTHER))
    act(() => result.current.handleUnauthorized('jwt-abc'))

    expect(result.current.session?.accountId).toBe('rmehta')
  })

  test('onSessionEnd fires when a session ends: sign-out, 401, or account switch', () => {
    const onSessionEnd = vi.fn()
    const { result } = setup(onSessionEnd)

    act(() => result.current.signIn(TOKEN))
    expect(onSessionEnd).not.toHaveBeenCalled() // first sign-in ends nothing

    act(() => result.current.signIn(OTHER))
    expect(onSessionEnd).toHaveBeenCalledTimes(1)

    act(() => result.current.handleUnauthorized('jwt-xyz'))
    expect(onSessionEnd).toHaveBeenCalledTimes(2)

    act(() => result.current.signIn(TOKEN))
    act(() => result.current.signOut())
    expect(onSessionEnd).toHaveBeenCalledTimes(3)
  })

  test('onSessionEnd does not fire for no-ops: signing out twice, or a stale 401', () => {
    const onSessionEnd = vi.fn()
    const { result } = setup(onSessionEnd)

    act(() => result.current.signOut())
    act(() => result.current.signIn(TOKEN))
    act(() => result.current.handleUnauthorized('jwt-someone-else'))

    expect(onSessionEnd).not.toHaveBeenCalled()
    expect(result.current.session).not.toBeNull()
  })

  test('endedBy records why the last session ended, and resets on the next sign-in', () => {
    const { result } = setup()
    expect(result.current.endedBy).toBeNull() // a fresh load: nothing has ended yet

    act(() => result.current.signIn(TOKEN))
    act(() => result.current.handleUnauthorized('jwt-abc'))
    expect(result.current.endedBy).toBe('expired')

    act(() => result.current.signIn(TOKEN))
    expect(result.current.endedBy).toBeNull()

    act(() => result.current.signOut())
    expect(result.current.endedBy).toBe('signOut')
  })

  test('rule 13: the token never reaches localStorage, sessionStorage or a cookie', () => {
    const { result } = setup()

    act(() => result.current.signIn(TOKEN))
    act(() => result.current.signIn(OTHER))

    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    expect(document.cookie).toBe('')
  })

  test('rule 13: a fresh mount (a hard refresh) starts signed out again', () => {
    const first = setup()
    act(() => first.result.current.signIn(TOKEN))
    first.unmount()

    const second = setup()

    expect(second.result.current.session).toBeNull()
    expect(second.result.current.getToken()).toBeNull()
  })

  test('useAuth outside an AuthProvider fails loudly rather than acting signed out', () => {
    function Orphan() {
      useAuth()
      return null
    }
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<Orphan />)).toThrow(/AuthProvider/)
    quiet.mockRestore()
  })
})
