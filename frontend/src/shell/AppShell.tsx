import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import { matchPath, NavLink, Outlet, useLocation } from 'react-router-dom'
import { displayNameFor } from '../auth/accounts'
import { useAuth, type Session } from '../auth/AuthContext'
import { pathToLot, pathToPart, SCREENS, screenById, type ScreenId } from '../screens/registry'
import {
  ChartSquareIcon,
  ChipIcon,
  FileUploadIcon,
  FolderIcon,
  GearIcon,
  GridIcon,
  HistoryIcon,
  UserIcon,
} from './icons'
import { WorkingLotContext, type WorkingLot } from './WorkingLotContext'

const NAV_ICONS: Partial<Record<ScreenId, () => ReactNode>> = {
  ingest: FileUploadIcon,
  lotDashboard: GridIcon,
  partDetail: ChartSquareIcon,
  projects: FolderIcon,
  history: HistoryIcon,
  settings: GearIcon,
}

/** Why an id-bound nav item is disabled, read by screen readers and shown on hover. */
const NEEDS_ID: Partial<Record<ScreenId, string>> = {
  lotDashboard: 'Ingest or open a lot first',
  partDetail: 'Open a part from a lot first',
}

/** The screen the current URL is on, for the breadcrumb. */
function currentScreen(pathname: string) {
  return SCREENS.find((s) => s.id !== 'login' && matchPath(s.path, pathname)) ?? null
}

/** Top-right account button: who is signed in, and Sign out. */
function AccountMenu({ session, onSignOut }: { session: Session; onSignOut: () => void }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const menuId = useId()

  useEffect(() => {
    if (!open) return
    function onPointer(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false)
        buttonRef.current?.focus()
      }
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div
      className="account-menu"
      ref={rootRef}
      // Tabbing out of the menu closes it; moving between its own controls doesn't. A null
      // relatedTarget is ignored: Safari doesn't focus a clicked button, so clicking Sign out
      // there blurs the toggle to nothing, and outside clicks are the pointerdown handler's job.
      onBlur={(event) => {
        const next = event.relatedTarget as Node | null
        if (next && !event.currentTarget.contains(next)) setOpen(false)
      }}
    >
      <button
        ref={buttonRef}
        type="button"
        className="avatar-button"
        aria-label="Account menu"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((o) => !o)}
      >
        <UserIcon size={18} />
      </button>
      {open && (
        <div className="account-popover" id={menuId}>
          <p className="account-popover-name">{displayNameFor(session.accountId)}</p>
          <p className="account-popover-role">{session.role}</p>
          {/* RequireAuth does the redirect to Login once the session is gone. */}
          <button type="button" className="button button-secondary" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}

/** The one navigation shell every signed-in screen sits behind (E6). */
export function AppShell() {
  const { session, signOut } = useAuth()
  const { pathname } = useLocation()
  const [lastLotId, setLastLotId] = useState<string | null>(null)
  const [lastPartId, setLastPartId] = useState<string | null>(null)

  // A file dropped on any signed-in screen would otherwise be opened by the browser, navigating
  // away and ending the in-memory session (rule 13). Drop zones handle their own drops first.
  useEffect(() => {
    const block = (event: Event) => event.preventDefault()
    window.addEventListener('dragover', block)
    window.addEventListener('drop', block)
    return () => {
      window.removeEventListener('dragover', block)
      window.removeEventListener('drop', block)
    }
  }, [])

  // Opening a lot or part by URL makes it the one the nav points back to. Adjusting state while
  // rendering (not in an effect) is React's pattern for state derived from a changing input.
  const openLot = matchPath(screenById('lotDashboard').path, pathname)?.params.lotId
  const openPart = matchPath(screenById('partDetail').path, pathname)?.params.componentId
  if (openLot && openLot !== lastLotId) setLastLotId(openLot)
  if (openPart && openPart !== lastPartId) setLastPartId(openPart)

  const workingLot = useMemo<WorkingLot>(
    () => ({ lastLotId, lastPartId, rememberLot: setLastLotId }),
    [lastLotId, lastPartId],
  )

  const here = currentScreen(pathname)
  const targetFor = (id: ScreenId, path: string): string | null => {
    if (id === 'lotDashboard') return lastLotId === null ? null : pathToLot(lastLotId)
    if (id === 'partDetail') return lastPartId === null ? null : pathToPart(lastPartId)
    return path
  }

  return (
    <WorkingLotContext.Provider value={workingLot}>
      <div className="shell">
        <aside className="sidebar">
          <div className="sidebar-brand">
            <ChipIcon />
            <div>
              <p className="sidebar-brand-name">Burn-In Anomaly</p>
              <p className="sidebar-brand-sub">SIH 26170 System</p>
            </div>
          </div>

          <nav className="sidebar-nav" aria-label="Main">
            <p className="sidebar-section">Workspace</p>
            <ul>
              {SCREENS.filter((s) => s.inNav).map((s) => {
                const Icon = NAV_ICONS[s.id]
                const target = targetFor(s.id, s.path)
                const content = (
                  <>
                    {Icon && <Icon />}
                    <span>{s.title}</span>
                  </>
                )
                return (
                  <li key={s.id}>
                    {target === null ? (
                      <span
                        className="nav-item is-disabled"
                        aria-disabled="true"
                        title={NEEDS_ID[s.id]}
                      >
                        {content}
                        <span className="visually-hidden"> ({NEEDS_ID[s.id]})</span>
                      </span>
                    ) : (
                      <NavLink to={target} className="nav-item">
                        {content}
                      </NavLink>
                    )}
                  </li>
                )
              })}
            </ul>
          </nav>

          {session && (
            <div className="sidebar-account">
              <div>
                <p className="sidebar-account-name">{displayNameFor(session.accountId)}</p>
                <p className="sidebar-account-role">{session.role}</p>
              </div>
              <span className="avatar" aria-hidden="true">
                <UserIcon size={16} />
              </span>
            </div>
          )}
        </aside>

        <div className="shell-body">
          <header className="topbar">
            <nav aria-label="Breadcrumb" className="breadcrumb">
              <span aria-hidden="true">/</span>
              {here && <span aria-current="page">{here.title}</span>}
            </nav>
            {session && <AccountMenu session={session} onSignOut={signOut} />}
          </header>
          <main className="shell-main">
            <Outlet />
          </main>
        </div>
      </div>
    </WorkingLotContext.Provider>
  )
}
