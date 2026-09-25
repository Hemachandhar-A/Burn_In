import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { screenById } from '../screens/registry'

/** Every screen but Login needs a signed-in account (E10 step 2); no session -> Login. */
export function RequireAuth() {
  const { session } = useAuth()
  const location = useLocation()
  if (!session) {
    return <Navigate to={screenById('login').path} replace state={{ from: location }} />
  }
  return <Outlet />
}
