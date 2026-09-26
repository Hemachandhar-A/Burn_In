import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import * as authApi from '../api/auth'
import { ApiError } from '../api/errors'
import type { MOCK_TokenResponse } from '../api/mocks'
import { useAuth } from '../auth/AuthContext'
import { AuthProvider } from '../auth/AuthProvider'
import { LoginScreen } from './LoginScreen'

const TOKEN: MOCK_TokenResponse = {
  access_token: 'jwt-1',
  token_type: 'bearer',
  account_id: 'r.mehta',
  role: 'Reliability Engineer',
}

function SessionProbe() {
  const { session } = useAuth()
  return <output data-testid="session">{session ? session.accountId : 'none'}</output>
}

function renderLogin() {
  return render(
    <AuthProvider>
      <MemoryRouter>
        <LoginScreen />
        <SessionProbe />
      </MemoryRouter>
    </AuthProvider>,
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
    renderLogin()
    const group = screen.getByRole('group', { name: 'Select Account' })
    const radios = screen.getAllByRole('radio')
    expect(group).toContainElement(radios[0])
    expect(radios).toHaveLength(2)
    expect(screen.getByRole('radio', { name: /A\. Sharma.*Quality Engineer/ })).toBeChecked()
    expect(screen.getByRole('radio', { name: /R\. Mehta.*Reliability Engineer/ })).not.toBeChecked()
  })

  test('the PIN is a labelled, masked field', () => {
    renderLogin()
    expect(pin()).toHaveAttribute('type', 'password')
  })

  test('an empty PIN is caught before any request', () => {
    const login = vi.spyOn(authApi, 'login')
    renderLogin()
    fireEvent.click(signInButton())
    expect(screen.getByRole('alert')).toHaveTextContent('Enter your PIN.')
    expect(login).not.toHaveBeenCalled()
  })

  test('sends the selected account and PIN, then holds the session in memory', async () => {
    const login = vi.spyOn(authApi, 'login').mockResolvedValue(TOKEN)
    renderLogin()

    fireEvent.click(screen.getByRole('radio', { name: /R\. Mehta/ }))
    fireEvent.change(pin(), { target: { value: '5678' } })
    fireEvent.click(signInButton())

    expect(login).toHaveBeenCalledWith({ account_id: 'r.mehta', pin: '5678' })
    await waitFor(() => expect(session()).toBe('r.mehta'))
  })

  test('while signing in the button is disabled, so a double click sends one request', async () => {
    let resolve: (value: MOCK_TokenResponse) => void = () => {}
    const login = vi.spyOn(authApi, 'login').mockReturnValue(new Promise((r) => (resolve = r)))
    renderLogin()
    fireEvent.change(pin(), { target: { value: '1234' } })

    fireEvent.click(signInButton())
    fireEvent.click(signInButton())

    expect(signInButton()).toBeDisabled()
    expect(signInButton()).toHaveTextContent('Signing in…')
    expect(login).toHaveBeenCalledTimes(1)
    await act(async () => resolve({ ...TOKEN, account_id: 'a.sharma' }))
    expect(session()).toBe('a.sharma')
  })

  test('a wrong PIN shows the server message, clears the PIN, and stays signed out', async () => {
    vi.spyOn(authApi, 'login').mockRejectedValue(
      new ApiError(401, ['Incorrect PIN for this account.']),
    )
    renderLogin()
    fireEvent.change(pin(), { target: { value: '0000' } })
    fireEvent.click(signInButton())

    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect PIN for this account.')
    expect(pin()).toHaveValue('')
    expect(pin()).toHaveAttribute('aria-invalid', 'true')
    expect(signInButton()).toBeEnabled()
    expect(session()).toBe('none')
  })

  test('no readable response says so, rather than "Failed to fetch"', async () => {
    vi.spyOn(authApi, 'login').mockRejectedValue(new TypeError('Failed to fetch'))
    renderLogin()
    fireEvent.change(pin(), { target: { value: '1234' } })
    fireEvent.click(signInButton())
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'No readable response from the API server',
    )
  })

  test('switching account clears a previous error', async () => {
    vi.spyOn(authApi, 'login').mockRejectedValue(new ApiError(401, ['Incorrect PIN.']))
    renderLogin()
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
    render(
      <AuthProvider
        initialSession={{ token: 't', accountId: 'a.sharma', role: 'Quality Engineer' }}
      >
        <MemoryRouter>
          <LoginScreen />
          <Expire />
        </MemoryRouter>
      </AuthProvider>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'expire' }))
    expect(screen.getByRole('status')).toHaveTextContent('Your session ended. Sign in again')
  })
})
