import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, test } from 'vitest'
import App from './App'
import { AppRoutes } from './AppRoutes'
import type { Session } from './auth/AuthContext'
import { AuthProvider } from './auth/AuthProvider'
import { SCREENS } from './screens/registry'

const SESSION: Session = { token: 'jwt-abc', accountId: 'asharma', role: 'Quality Engineer' }

function renderAt(path: string, session: Session | null = SESSION) {
  return render(
    <AuthProvider initialSession={session}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </AuthProvider>,
  )
}

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
    expect(screen.getByRole('heading', { level: 1, name: title })).toBeInTheDocument()
  })

  test('/login renders the Login screen when signed out', () => {
    renderAt('/login', null)
    expect(screen.getByRole('heading', { level: 1, name: 'Login' })).toBeInTheDocument()
  })

  test('route params reach the screen (Lot Dashboard shows which lot)', () => {
    renderAt('/lots/LOT-001')
    expect(screen.getByText(/LOT-001/)).toBeInTheDocument()
  })
})

describe('auth guard (rule 13)', () => {
  test.each(['/ingest', '/lots/LOT-001', '/parts/C1', '/projects', '/history', '/settings'])(
    'signed out, %s redirects to Login',
    (path) => {
      renderAt(path, null)
      expect(screen.getByRole('heading', { level: 1, name: 'Login' })).toBeInTheDocument()
    },
  )

  test('signed in, / lands on Ingest', () => {
    renderAt('/')
    expect(screen.getByRole('heading', { level: 1, name: 'Ingest' })).toBeInTheDocument()
  })

  test('signed in, /login forwards to Ingest instead of showing Login again', () => {
    renderAt('/login')
    expect(screen.getByRole('heading', { level: 1, name: 'Ingest' })).toBeInTheDocument()
  })

  test('an unknown path shows a not-found message, not a blank page', () => {
    renderAt('/nope')
    expect(screen.getByRole('heading', { level: 1, name: 'Page not found' })).toBeInTheDocument()
  })

  test('the full app on a fresh load starts at Login (a hard refresh re-prompts)', () => {
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: 'Login' })).toBeInTheDocument()
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

  test('nav links move between screens', () => {
    renderAt('/ingest')
    fireEvent.click(screen.getByRole('link', { name: 'History' }))
    expect(screen.getByRole('heading', { level: 1, name: 'History' })).toBeInTheDocument()
  })

  test('Sign out discards the session and returns to Login, without the nav shell', () => {
    renderAt('/settings')
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(screen.getByRole('heading', { level: 1, name: 'Login' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).toBeNull()
  })
})
