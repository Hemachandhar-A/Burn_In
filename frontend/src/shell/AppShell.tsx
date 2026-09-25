import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { SCREENS } from '../screens/registry'

/** The one navigation shell every signed-in screen sits behind (E6). */
export function AppShell() {
  const { session, signOut } = useAuth()

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
            {/* RequireAuth does the redirect to Login once the session is gone. */}
            <button type="button" onClick={signOut}>
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
