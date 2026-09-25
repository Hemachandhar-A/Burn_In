import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { SCREENS, screenById } from '../screens/registry'

/** The one navigation shell every signed-in screen sits behind (E6). */
export function AppShell() {
  const { session, signOut } = useAuth()
  const navigate = useNavigate()

  function handleSignOut() {
    signOut()
    navigate(screenById('login').path, { replace: true })
  }

  return (
    <div className="shell">
      <header className="shell-header">
        <span className="shell-title">Burn-In Screening</span>
        <nav aria-label="Main">
          {SCREENS.filter((s) => s.inNav).map((s) => (
            <NavLink key={s.id} to={s.path}>
              {s.title}
            </NavLink>
          ))}
        </nav>
        {session && (
          <div className="shell-account">
            <span className="shell-account-id">{session.accountId}</span>
            <span className="shell-account-role">{session.role}</span>
            <button type="button" onClick={handleSignOut}>
              Sign out
            </button>
          </div>
        )}
      </header>
      <main className="shell-main">
        <Outlet />
      </main>
    </div>
  )
}
