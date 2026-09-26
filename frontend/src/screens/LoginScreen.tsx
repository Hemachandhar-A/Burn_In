import { useId, useRef, useState, type FormEvent } from 'react'
import { login } from '../api/auth'
import { describeFailure } from '../api/errors'
import { TEMP_LOGIN_ACCOUNTS } from '../auth/accounts'
import { useAuth } from '../auth/AuthContext'

/** Decorative only: two lots holding flat, one drifting away. The page's subject in one glance. */
function DriftSketch() {
  return (
    <svg className="login-sketch" viewBox="0 0 400 120" aria-hidden="true" focusable="false">
      <path d="M0 108 L400 84" className="login-sketch-flat" />
      <path d="M0 113 L400 88" className="login-sketch-flat" />
      <path d="M0 106 C 120 100, 200 88, 290 50 S 370 12, 400 6" className="login-sketch-drift" />
    </svg>
  )
}

/**
 * E6 screen 1: pick one of the two named accounts (E10), enter its PIN. The JWT that comes back
 * goes into AuthContext's in-memory state only (rule 13), so a hard refresh lands back here.
 * AppRoutes moves on to the requested screen as soon as the session exists.
 */
export function LoginScreen() {
  const { signIn, endedBy } = useAuth()
  const [accountId, setAccountId] = useState(TEMP_LOGIN_ACCOUNTS[0].account_id)
  const [pin, setPin] = useState('')
  const [errors, setErrors] = useState<string[]>([])
  const [pending, setPending] = useState(false)
  // A ref, not the state above: two clicks in one tick both see pending === false.
  const inFlight = useRef(false)
  const pinRef = useRef<HTMLInputElement>(null)
  const ids = { pin: useId(), error: useId(), intro: useId() }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (inFlight.current) return
    if (pin.trim() === '') {
      setErrors(['Enter your PIN.'])
      pinRef.current?.focus()
      return
    }
    inFlight.current = true
    setPending(true)
    setErrors([])
    try {
      signIn(await login({ account_id: accountId, pin }))
    } catch (error) {
      setErrors(describeFailure(error))
      setPin('')
      pinRef.current?.focus()
    } finally {
      inFlight.current = false
      setPending(false)
    }
  }

  function selectAccount(id: string) {
    setAccountId(id)
    setErrors([])
  }

  const invalid = errors.length > 0

  return (
    <div className="login">
      <aside className="login-panel">
        <h1 className="login-title">Burn-In Anomaly Detection System</h1>
        <p className="login-lede">
          Physics-grounded anomaly detection and early drift prediction for semiconductor burn-in
          qualification.
        </p>
        <DriftSketch />
        <p className="login-footnote">SIH 26170</p>
      </aside>

      <main className="login-main">
        <form className="login-form" onSubmit={submit} noValidate>
          {endedBy === 'expired' && (
            <p className="login-notice" role="status">
              Your session ended. Sign in again to continue where you left off.
            </p>
          )}

          <fieldset className="login-accounts" aria-describedby={ids.intro}>
            <legend className="login-heading">Select Account</legend>
            <p className="login-intro" id={ids.intro}>
              Sign in using an authorized engineering profile.
            </p>
            {TEMP_LOGIN_ACCOUNTS.map((account) => (
              <label key={account.account_id} className="account-option">
                <span className="account-option-text">
                  <span className="account-option-name">{account.display_name}</span>
                  <span className="visually-hidden">, </span>
                  <span className="account-option-role">{account.role}</span>
                </span>
                <input
                  type="radio"
                  name="account"
                  value={account.account_id}
                  checked={accountId === account.account_id}
                  onChange={() => selectAccount(account.account_id)}
                  disabled={pending}
                />
              </label>
            ))}
          </fieldset>

          <label className="field-label" htmlFor={ids.pin}>
            PIN
          </label>
          <input
            ref={pinRef}
            id={ids.pin}
            className="login-pin"
            type="password"
            inputMode="numeric"
            autoComplete="off"
            placeholder="••••"
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            aria-invalid={invalid}
            aria-describedby={invalid ? ids.error : undefined}
            // readOnly, not disabled: a disabled field can't take focus, and a failed attempt
            // hands focus back here before the pending state has re-rendered.
            readOnly={pending}
          />
          {invalid && (
            <div className="form-error" id={ids.error} role="alert">
              {errors.map((line, i) => (
                // Index keys: a server can repeat the same message.
                <p key={i}>{line}</p>
              ))}
            </div>
          )}

          <button type="submit" className="button button-primary login-submit" disabled={pending}>
            {pending ? 'Signing in…' : 'Sign In'}
          </button>
        </form>
      </main>
    </div>
  )
}
