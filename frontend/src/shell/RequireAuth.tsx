import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { screenById } from '../screens/registry'
import type { ReturnState } from './returnTarget'

/**
 * Every screen but Login needs a signed-in account (E10 step 2); no session -> Login. The page
 * is remembered for after sign-in on a fresh load or an expired session - not after a
 * deliberate Sign out, so the next account doesn't land on the previous one's page.
 */
export function RequireAuth() {
  const { session, endedBy } = useAuth()
  const location = useLocation()
  if (!session) {
    const state: ReturnState | null =
      endedBy === 'signOut'
        ? null
        : { from: { pathname: location.pathname, search: location.search, hash: location.hash } }
    return <Navigate to={screenById('login').path} replace state={state} />
  }
  return <Outlet />
}
