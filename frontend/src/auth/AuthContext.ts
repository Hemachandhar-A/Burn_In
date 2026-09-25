import { createContext, useContext } from 'react'

/**
 * Local mirror of contracts.py `TokenResponse` (Part 5.6). TEMP_ because `POST /auth/login`
 * isn't registered in api/main.py yet (lands in P5.4), so the generated schema has no
 * `components['schemas']['TokenResponse']` to import. Swap this for the generated type the
 * first time `npm run generate-client` picks up that route (P1.10).
 */
export interface TEMP_TokenResponse {
  access_token: string
  token_type: 'bearer'
  account_id: string
  role: string
}

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
  signIn: (response: TEMP_TokenResponse) => void
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
