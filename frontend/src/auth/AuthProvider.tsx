import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { AuthContext, type AuthState, type Session, type TEMP_TokenResponse } from './AuthContext'

interface AuthProviderProps {
  children: ReactNode
  /** Tests only: start already signed in. Still plain React state, never persisted. */
  initialSession?: Session | null
}

/**
 * Holds the JWT in React state and nowhere else (AGENTS.md rule 13) - no localStorage,
 * sessionStorage or cookie, so a hard refresh drops it and the app returns to Login.
 * A disclosed trade-off (context.md Part 8.1), not a bug to "fix" by persisting it.
 */
export function AuthProvider({ children, initialSession = null }: AuthProviderProps) {
  const [session, setSession] = useState<Session | null>(initialSession)

  const signIn = useCallback((response: TEMP_TokenResponse) => {
    setSession({
      token: response.access_token,
      accountId: response.account_id,
      role: response.role,
    })
  }, [])

  const signOut = useCallback(() => setSession(null), [])

  const value = useMemo<AuthState>(() => ({ session, signIn, signOut }), [session, signIn, signOut])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
