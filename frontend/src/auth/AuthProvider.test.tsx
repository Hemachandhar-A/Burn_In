import { act, render, renderHook, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, test } from 'vitest'
import { useAuth, type TEMP_TokenResponse } from './AuthContext'
import { AuthProvider } from './AuthProvider'

const TOKEN: TEMP_TokenResponse = {
  access_token: 'jwt-abc',
  token_type: 'bearer',
  account_id: 'asharma',
  role: 'Quality Engineer',
}

const wrapper = ({ children }: { children: ReactNode }) => <AuthProvider>{children}</AuthProvider>

afterEach(() => {
  localStorage.clear()
  sessionStorage.clear()
})

describe('AuthProvider', () => {
  test('starts signed out', () => {
    const { result } = renderHook(() => useAuth(), { wrapper })
    expect(result.current.session).toBeNull()
  })

  test('signIn holds the token, account and role from the login response', () => {
    const { result } = renderHook(() => useAuth(), { wrapper })

    act(() => result.current.signIn(TOKEN))

    expect(result.current.session).toEqual({
      token: 'jwt-abc',
      accountId: 'asharma',
      role: 'Quality Engineer',
    })
  })

  test('signOut discards the token', () => {
    const { result } = renderHook(() => useAuth(), { wrapper })

    act(() => result.current.signIn(TOKEN))
    act(() => result.current.signOut())

    expect(result.current.session).toBeNull()
  })

  test('rule 13: the token never reaches localStorage, sessionStorage or a cookie', () => {
    const { result } = renderHook(() => useAuth(), { wrapper })

    act(() => result.current.signIn(TOKEN))

    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    expect(document.cookie).toBe('')
  })

  test('rule 13: a fresh mount (a hard refresh) starts signed out again', () => {
    const first = renderHook(() => useAuth(), { wrapper })
    act(() => first.result.current.signIn(TOKEN))
    first.unmount()

    const second = renderHook(() => useAuth(), { wrapper })

    expect(second.result.current.session).toBeNull()
  })

  test('useAuth outside an AuthProvider fails loudly rather than acting signed out', () => {
    function Orphan() {
      useAuth()
      return null
    }
    expect(() => render(<Orphan />)).toThrow(/AuthProvider/)
    expect(screen.queryByText(/./)).toBeNull()
  })
})
