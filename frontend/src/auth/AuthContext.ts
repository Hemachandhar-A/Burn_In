import { createContext, useContext } from 'react'
import type { TokenResponse } from '../api/auth'

export type { TokenResponse }

export interface Session {
  token: string
  accountId: string
  role: string
}

/** Why the last session ended: a deliberate Sign out, or the server rejecting the token (401). */
export type SessionEnd = 'signOut' | 'expired'

export interface AuthState {
  session: Session | null
  /** null on a fresh load and while signed in. */
  endedBy: SessionEnd | null
  /** Throws on a response that couldn't authenticate anything (blank token, non-bearer). */
  signIn: (response: TokenResponse) => void
  signOut: () => void
  /** Stable across renders; returns the token at call time, for the API client's requests. */
  getToken: () => string | null
  /** A 401 came back for `rejectedToken`: sign out, unless a newer session has replaced it. */
  handleUnauthorized: (rejectedToken: string) => void
}

export const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const auth = useContext(AuthContext)
  if (!auth) throw new Error('useAuth must be used inside an <AuthProvider>')
  return auth
}
