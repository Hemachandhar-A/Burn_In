import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { describe, expect, test } from 'vitest'
import { AppRoutes } from './AppRoutes'
import { useAuth, type Session, type TokenResponse } from './auth/AuthContext'
import { AuthProvider } from './auth/AuthProvider'
import { pathToLot, pathToPart, SCREENS } from './screens/registry'

const SESSION: Session = { token: 'jwt-abc', accountId: 'asharma', role: 'Quality Engineer' }
const LOGIN: TokenResponse = {
  access_token: 'jwt-new',
  token_type: 'bearer',
  account_id: 'rmehta',
  role: 'Reliability Engineer',
}

/** Test-only controls standing in for P1.10's Login form and for a server-side 401. */
function Harness() {
  const auth = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  return (
    <div>
      <button onClick={() => auth.signIn(LOGIN)}>test: sign in</button>
      <button onClick={() => auth.session && auth.handleUnauthorized(auth.session.token)}>
        test: expire session
      </button>
      <button onClick={() => navigate(-1)}>test: back</button>
      <output data-testid="location">{location.pathname + location.search + location.hash}</output>
    </div>
  )
}

function renderAt(path: string | string[], session: Session | null = SESSION) {
  const entries = Array.isArray(path) ? path : [path]
  return render(
    <AuthProvider initialSession={session}>
      <MemoryRouter initialEntries={entries} initialIndex={entries.length - 1}>
        <AppRoutes />
        <Harness />
      </MemoryRouter>
    </AuthProvider>,
  )
}

/** Login's page heading is the product name (per its design); its form is the "Select Account" group. */
const h1 = (name: string) =>
  name === 'Login'
    ? screen.getByRole('group', { name: 'Select Account' })
    : screen.getByRole('heading', { level: 1, name })
const click = (name: string) => act(() => fireEvent.click(screen.getByRole('button', { name })))
const location = () => screen.getByTestId('location').textContent

describe('screen inventory (E6)', () => {
  test('names exactly the seven E6 screens, in E6 order', () => {
    expect(SCREENS.map((s) => s.title)).toEqual([
      'Login',
      'Ingest',
      'Lot Dashboard',
      'Part Detail',
      'Project Browser',
      'History',
      'Settings',
    ])
  })

  test.each([
    ['/ingest', 'Ingest'],
    ['/lots/LOT-001', 'Lot Dashboard'],
    ['/parts/LOT-001-C0042', 'Part Detail'],
    ['/projects', 'Project Browser'],
    ['/history', 'History'],
    ['/settings', 'Settings'],
  ])('%s renders the %s screen when signed in', (path, title) => {
    renderAt(path)
    expect(h1(title)).toBeInTheDocument()
  })

  test('/login renders the Login screen when signed out', () => {
    renderAt('/login', null)
    expect(h1('Login')).toBeInTheDocument()
  })

  test.each(['/settings/', '/lots/LOT-001/'])('a trailing slash (%s) still matches', (path) => {
    renderAt(path)
    expect(screen.queryByRole('heading', { level: 1, name: 'Page not found' })).toBeNull()
  })

  test.each(['/lots/', '/parts/', '/lots/A/extra', '/nope'])(
    'signed in, %s shows Page not found rather than a blank or wrong screen',
    (path) => {
      renderAt(path)
      expect(h1('Page not found')).toBeInTheDocument()
    },
  )
})

describe('ids in URLs', () => {
  test.each(['LOT-001', 'LOT 1', 'A/B', 'x#y', 'q?r', '100%', 'Ünïcødé-λ', '.', '..'])(
    'lot id %j round-trips through its Lot Dashboard URL',
    (id) => {
      renderAt(pathToLot(id))
      expect(h1('Lot Dashboard')).toBeInTheDocument()
      expect(screen.getByTestId('route-id')).toHaveTextContent(id, { normalizeWhitespace: false })
    },
  )

  test.each(['C0042', 'A/B', 'x#y', '100%'])(
    'component id %j round-trips through its Part Detail URL',
    (id) => {
      renderAt(pathToPart(id))
      expect(h1('Part Detail')).toBeInTheDocument()
      expect(screen.getByTestId('route-id')).toHaveTextContent(id, { normalizeWhitespace: false })
    },
  )

  test('a malformed escape in a hand-typed URL does not crash the app', () => {
    renderAt('/lots/%E0%A4%A')
    expect(h1('Lot Dashboard')).toBeInTheDocument()
  })
})

describe('auth guard (rule 13)', () => {
  test.each([
    '/ingest',
    '/lots/LOT-001',
    '/parts/C1',
    '/projects',
    '/history',
    '/settings',
    '/nope',
  ])('signed out, %s redirects to Login', (path) => {
    renderAt(path, null)
    expect(h1('Login')).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).toBeNull()
  })

  test('signed in, / lands on Ingest', () => {
    renderAt('/')
    expect(h1('Ingest')).toBeInTheDocument()
  })

  test('signed in, /login forwards to Ingest instead of showing Login again', () => {
    renderAt('/login')
    expect(h1('Ingest')).toBeInTheDocument()
  })

  test('signing in after a redirect returns to the page asked for, query and hash intact', () => {
    renderAt('/lots/LOT-7?view=early#ranked', null)
    expect(h1('Login')).toBeInTheDocument()

    click('test: sign in')

    expect(h1('Lot Dashboard')).toBeInTheDocument()
    expect(location()).toBe('/lots/LOT-7?view=early#ranked')
  })

  test('signing in straight from /login lands on Ingest', () => {
    renderAt('/login', null)
    click('test: sign in')
    expect(h1('Ingest')).toBeInTheDocument()
  })

  test('an expired session (401) goes to Login, and signing back in resumes the page', () => {
    renderAt('/settings')
    click('test: expire session')
    expect(h1('Login')).toBeInTheDocument()

    click('test: sign in')

    expect(h1('Settings')).toBeInTheDocument()
    expect(screen.getByText('rmehta')).toBeInTheDocument()
  })

  test('an explicit Sign out does not bounce the next account back to the old page', () => {
    renderAt('/settings')
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    click('test: sign in')
    expect(h1('Ingest')).toBeInTheDocument()
  })

  test('Back after Sign out cannot reopen a guarded screen', () => {
    renderAt(['/ingest', '/settings'])
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))

    click('test: back')

    expect(h1('Login')).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).toBeNull()
  })
})

describe('navigation shell', () => {
  test('shows the signed-in account and role', () => {
    renderAt('/ingest')
    expect(screen.getByText('asharma')).toBeInTheDocument()
    expect(screen.getByText('Quality Engineer')).toBeInTheDocument()
  })

  test('links the four top-level screens; Lot Dashboard and Part Detail are reached from data', () => {
    renderAt('/ingest')
    const nav = screen.getByRole('navigation')
    const labels = Array.from(nav.querySelectorAll('a')).map((a) => a.textContent)
    expect(labels).toEqual(['Ingest', 'Project Browser', 'History', 'Settings'])
  })

  test('marks only the current screen as the active nav link', () => {
    renderAt('/history')
    expect(screen.getByRole('link', { name: 'History' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Ingest' })).not.toHaveAttribute('aria-current')
  })

  test('nav links move between screens', () => {
    renderAt('/ingest')
    fireEvent.click(screen.getByRole('link', { name: 'History' }))
    expect(h1('History')).toBeInTheDocument()
  })

  test('Sign out discards the session and returns to Login, without the nav shell', () => {
    renderAt('/settings')
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(h1('Login')).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).toBeNull()
  })
})
