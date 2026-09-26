import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  AuthContext,
  type AuthState,
  type Session,
  type SessionEnd,
  type TokenResponse,
} from './AuthContext'

interface AuthProviderProps {
  children: ReactNode
  /** Tests only: start already signed in. Still plain React state, never persisted. */
  initialSession?: Session | null
  /** Fires whenever a session ends - sign-out, a 401, or another account signing in over it. */
  onSessionEnd?: () => void
}

function toSession(response: TokenResponse): Session {
  const token = response.access_token?.trim()
  const accountId = response.account_id?.trim()
  if (!token || response.token_type !== 'bearer' || !accountId) {
    throw new Error('Rejected a login response with no usable bearer token or account id')
  }
  return { token, accountId, role: response.role }
}

/**
 * Holds the JWT in React state and nowhere else (AGENTS.md rule 13) - no web storage and no
 * cookie, so a hard refresh drops it and the app returns to Login. A disclosed trade-off
 * (context.md Part 8.1), not a bug to "fix" by persisting it.
 *
 * The token is mirrored in a ref, written only when a session starts or ends, so the API client
 * can read the current one per request without being rebuilt (and without in-flight requests
 * holding a stale token).
 */
export function AuthProvider({ children, initialSession = null, onSessionEnd }: AuthProviderProps) {
  const [session, setSession] = useState<Session | null>(initialSession)
  const [endedBy, setEndedBy] = useState<SessionEnd | null>(null)
  const tokenRef = useRef<string | null>(initialSession?.token ?? null)

  const signIn = useCallback(
    (response: TokenResponse) => {
      const next = toSession(response)
      const replacing = tokenRef.current !== null
      tokenRef.current = next.token
      setSession(next)
      setEndedBy(null)
      if (replacing) onSessionEnd?.()
    },
    [onSessionEnd],
  )

  const endSession = useCallback(
    (reason: SessionEnd) => {
      if (tokenRef.current === null) return
      tokenRef.current = null
      setSession(null)
      setEndedBy(reason)
      onSessionEnd?.()
    },
    [onSessionEnd],
  )

  const signOut = useCallback(() => endSession('signOut'), [endSession])

  const getToken = useCallback(() => tokenRef.current, [])

  const handleUnauthorized = useCallback(
    (rejectedToken: string) => {
      if (tokenRef.current !== null && tokenRef.current === rejectedToken) endSession('expired')
    },
    [endSession],
  )

  const value = useMemo<AuthState>(
    () => ({ session, endedBy, signIn, signOut, getToken, handleUnauthorized }),
    [session, endedBy, signIn, signOut, getToken, handleUnauthorized],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
