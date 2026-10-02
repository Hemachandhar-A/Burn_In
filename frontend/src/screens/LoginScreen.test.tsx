import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { fakeServer, renderWithApi } from '../test-utils'
import { useAuth } from '../auth/AuthContext'
import { LoginScreen } from './LoginScreen'

function SessionProbe() {
  const { session } = useAuth()
  return <output data-testid="session">{session ? session.accountId : 'none'}</output>
}

function renderLogin(fetch: (r: Request) => Promise<Response>) {
  return renderWithApi(
    <>
      <LoginScreen />
      <SessionProbe />
    </>,
    { fetch, session: null },
  )
}

const pin = () => screen.getByLabelText('PIN')
const signInButton = () => screen.getByRole('button', { name: /^sign(ing)? in/i })
const session = () => screen.getByTestId('session').textContent

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('Login screen (E6 screen 1)', () => {
  test('offers exactly the two named accounts, by name and fixed role, first one selected', () => {
    renderLogin(fakeServer({}).fetch)
    const group = screen.getByRole('group', { name: 'Select Account' })
    const radios = screen.getAllByRole('radio')
    expect(group).toContainElement(radios[0])
    expect(radios).toHaveLength(2)
    expect(screen.getByRole('radio', { name: /A\. Sharma.*Quality Engineer/ })).toBeChecked()
    expect(screen.getByRole('radio', { name: /R\. Mehta.*Reliability Engineer/ })).not.toBeChecked()
  })

  test('the PIN is a labelled, masked field', () => {
    renderLogin(fakeServer({}).fetch)
    expect(pin()).toHaveAttribute('type', 'password')
  })

  test('an empty PIN is caught before any request', () => {
    const { fetch, requests } = fakeServer({})
    renderLogin(fetch)
    fireEvent.click(signInButton())
    expect(screen.getByRole('alert')).toHaveTextContent('Enter your PIN.')
    expect(requests).toHaveLength(0)
  })

  test('sends the selected account and PIN, then holds the session in memory', async () => {
    const { fetch, requests } = fakeServer({
      'POST /auth/login': {
        body: {
          access_token: 'jwt-1',
          token_type: 'bearer',
          account_id: 'r.mehta',
          role: 'Reliability Engineer',
        },
      },
    })
    renderLogin(fetch)

    fireEvent.click(screen.getByRole('radio', { name: /R\. Mehta/ }))
    fireEvent.change(pin(), { target: { value: '5678' } })
    fireEvent.click(signInButton())

    await waitFor(() => expect(session()).toBe('r.mehta'))
    expect(await requests[0].json()).toEqual({ account_id: 'r.mehta', pin: '5678' })
  })

  test('while signing in the button is disabled, so a double click sends one request', async () => {
    let resolve: (value: Response) => void = () => {}
    let calls = 0
    const fetch = vi.fn(
      () =>
        new Promise<Response>((r) => {
          calls++
          resolve = r
        }),
    )
    renderLogin(fetch)
    fireEvent.change(pin(), { target: { value: '1234' } })

    fireEvent.click(signInButton())
    fireEvent.click(signInButton())

    expect(signInButton()).toBeDisabled()
    expect(signInButton()).toHaveTextContent('Signing in…')
    await waitFor(() => expect(calls).toBe(1))
    await waitFor(() =>
      resolve(
        new Response(
          JSON.stringify({
            access_token: 'jwt-1',
            token_type: 'bearer',
            account_id: 'a.sharma',
            role: 'Quality Engineer',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )
    await waitFor(() => expect(session()).toBe('a.sharma'))
  })

  test('a wrong PIN shows the server message, clears the PIN, and stays signed out', async () => {
    const { fetch } = fakeServer({
      'POST /auth/login': { status: 401, body: { detail: 'Incorrect PIN for this account.' } },
    })
    renderLogin(fetch)
    fireEvent.change(pin(), { target: { value: '0000' } })
    fireEvent.click(signInButton())

    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect PIN for this account.')
    expect(pin()).toHaveValue('')
    expect(pin()).toHaveAttribute('aria-invalid', 'true')
    expect(signInButton()).toBeEnabled()
    expect(session()).toBe('none')
    // Focus goes back to the PIN, so a keyboard user can retype straight away. (A disabled
    // field can't take focus, so this only works if the PIN isn't disabled while pending.)
    expect(pin()).toHaveFocus()
  })

  test('a whitespace-only PIN counts as empty and is never sent', () => {
    const { fetch, requests } = fakeServer({})
    renderLogin(fetch)
    fireEvent.change(pin(), { target: { value: '   ' } })
    fireEvent.click(signInButton())
    expect(screen.getByRole('alert')).toHaveTextContent('Enter your PIN.')
    expect(requests).toHaveLength(0)
  })

  test('while signing in the PIN cannot be edited, but stays focusable', () => {
    const fetch = vi.fn(() => new Promise<Response>(() => {}))
    renderLogin(fetch)
    fireEvent.change(pin(), { target: { value: '1234' } })
    fireEvent.click(signInButton())
    expect(pin()).toHaveAttribute('readonly')
    expect(pin()).toBeEnabled()
  })

  test('identical server messages are all shown, without key collisions', async () => {
    const errorSpy = vi.spyOn(console, 'error')
    const { fetch } = fakeServer({
      'POST /auth/login': { status: 401, body: { detail: ['Nope.', 'Nope.'] } },
    })
    renderLogin(fetch)
    fireEvent.change(pin(), { target: { value: '0000' } })
    fireEvent.click(signInButton())
    const alert = await screen.findByRole('alert')
    expect(alert.querySelectorAll('p')).toHaveLength(2)
    expect(errorSpy).not.toHaveBeenCalled()
  })

  test('no readable response says so, rather than "Failed to fetch"', async () => {
    const fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))
    renderLogin(fetch)
    fireEvent.change(pin(), { target: { value: '1234' } })
    fireEvent.click(signInButton())
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'No readable response from the API server',
    )
  })

  test('switching account clears a previous error', async () => {
    const { fetch } = fakeServer({
      'POST /auth/login': { status: 401, body: { detail: 'Incorrect PIN.' } },
    })
    renderLogin(fetch)
    fireEvent.change(pin(), { target: { value: '0000' } })
    fireEvent.click(signInButton())
    await screen.findByRole('alert')

    fireEvent.click(screen.getByRole('radio', { name: /R\. Mehta/ }))

    expect(screen.queryByRole('alert')).toBeNull()
  })

  test('a session that expired (401) is explained, not silently dropped', () => {
    function Expire() {
      const auth = useAuth()
      return (
        <button onClick={() => auth.handleUnauthorized('t')} type="button">
          expire
        </button>
      )
    }
    renderWithApi(
      <>
        <LoginScreen />
        <Expire />
      </>,
      {
        fetch: fakeServer({}).fetch,
        session: { token: 't', accountId: 'a.sharma', role: 'Quality Engineer' },
      },
    )
    fireEvent.click(screen.getByRole('button', { name: 'expire' }))
    expect(screen.getByRole('status')).toHaveTextContent('Your session ended. Sign in again')
  })
})
