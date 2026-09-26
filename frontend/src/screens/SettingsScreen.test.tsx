import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { ApiError } from '../api/errors'
import { MOCK_FIXTURE_PROJECTS, MOCK_resetStores } from '../api/mocks'
import * as settingsApi from '../api/settings'
import { fakeServer, renderWithApi } from '../test-utils'
import { SettingsScreen } from './SettingsScreen'

const R_MEHTA = { token: 't', accountId: 'r.mehta', role: 'Reliability Engineer' }

function server() {
  return fakeServer({ 'GET /projects': { body: MOCK_FIXTURE_PROJECTS } }).fetch
}

function card(name: RegExp) {
  return screen.getByRole('region', { name })
}

async function loaded() {
  await screen.findByRole('region', { name: /fn:fp cost ratio/i })
  await within(card(/fn:fp cost ratio/i)).findByText('10:1')
}

beforeEach(() => {
  vi.restoreAllMocks()
  MOCK_resetStores()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('SettingsScreen (E6 screen 7)', () => {
  test('shows the three live values, and a pending change distinct from the finalized one', async () => {
    renderWithApi(<SettingsScreen />, { fetch: server() })
    await loaded()

    expect(within(card(/confirmed-outcome fn ceiling/i)).getByText('5.0%')).toBeInTheDocument()
    const pda = card(/pda threshold/i)
    expect(pda).toHaveClass('is-pending')
    expect(within(pda).getByText('5.0%')).toBeInTheDocument()
    expect(within(pda).getByText('Pending second sign-off')).toBeInTheDocument()
    expect(within(pda).getByText(/proposed 5\.5% by r\. mehta/i)).toBeInTheDocument()
    // No second proposal while one is pending for the same value.
    expect(within(pda).queryByRole('button', { name: /edit/i })).not.toBeInTheDocument()
    expect(card(/fn:fp cost ratio/i)).not.toHaveClass('is-pending')
  })

  test('proposing a ratio change makes it pending, not final, and logs it to History', async () => {
    const propose = vi.spyOn(settingsApi, 'proposeSetting')
    renderWithApi(<SettingsScreen />, { fetch: server() })
    await loaded()

    const ratio = card(/fn:fp cost ratio/i)
    fireEvent.click(within(ratio).getByRole('button', { name: /edit/i }))
    const input = within(ratio).getByLabelText(/proposed fn:fp cost ratio/i)
    fireEvent.change(input, { target: { value: '12' } })
    fireEvent.click(within(ratio).getByRole('button', { name: /propose/i }))

    expect(await within(ratio).findByText(/proposed 12:1 by a\. sharma/i)).toBeInTheDocument()
    expect(propose).toHaveBeenCalledWith(
      { field: 'fn_fp_cost_ratio', proposed_value: 12 },
      'a.sharma',
    )
    expect(within(ratio).getByText('10:1')).toBeInTheDocument()
    expect(ratio).toHaveClass('is-pending')
    // The proposer can't also be the second sign-off.
    expect(within(ratio).queryByRole('button', { name: /sign off/i })).not.toBeInTheDocument()
    expect(
      within(ratio).getByText(/needs a second sign-off from a different account/i),
    ).toBeInTheDocument()
  })

  test('a percentage is typed as a percent and sent as a fraction', async () => {
    const propose = vi.spyOn(settingsApi, 'proposeSetting')
    renderWithApi(<SettingsScreen />, { fetch: server() })
    await loaded()

    const ceiling = card(/confirmed-outcome fn ceiling/i)
    fireEvent.click(within(ceiling).getByRole('button', { name: /edit/i }))
    const input = within(ceiling).getByLabelText(/proposed confirmed-outcome fn ceiling \(%\)/i)
    expect(input).toHaveValue('5')
    fireEvent.change(input, { target: { value: '4.5' } })
    fireEvent.click(within(ceiling).getByRole('button', { name: /propose/i }))

    await waitFor(() =>
      expect(propose).toHaveBeenCalledWith(
        { field: 'confirmed_outcome_fn_ceiling', proposed_value: 0.045 },
        'a.sharma',
      ),
    )
  })

  test.each([
    ['abc', /fn:fp cost ratio/i],
    ['0', /fn:fp cost ratio/i],
    ['', /fn:fp cost ratio/i],
    ['150', /confirmed-outcome fn ceiling/i],
    ['-3', /confirmed-outcome fn ceiling/i],
  ])('rejects %j before sending anything', async (value, name) => {
    const propose = vi.spyOn(settingsApi, 'proposeSetting')
    renderWithApi(<SettingsScreen />, { fetch: server() })
    await loaded()

    const target = card(name)
    fireEvent.click(within(target).getByRole('button', { name: /edit/i }))
    const input = within(target).getByRole('textbox')
    fireEvent.change(input, { target: { value } })
    fireEvent.click(within(target).getByRole('button', { name: /propose/i }))

    expect(await within(target).findByRole('alert')).toBeInTheDocument()
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(propose).not.toHaveBeenCalled()
  })

  test('cancel closes the form without proposing', async () => {
    const propose = vi.spyOn(settingsApi, 'proposeSetting')
    renderWithApi(<SettingsScreen />, { fetch: server() })
    await loaded()

    const ratio = card(/fn:fp cost ratio/i)
    fireEvent.click(within(ratio).getByRole('button', { name: /edit/i }))
    fireEvent.click(within(ratio).getByRole('button', { name: /cancel/i }))
    expect(within(ratio).queryByRole('textbox')).not.toBeInTheDocument()
    expect(within(ratio).getByRole('button', { name: /edit/i })).toHaveFocus()
    expect(propose).not.toHaveBeenCalled()
  })

  test('a different account signs off, and the value becomes final', async () => {
    const signoff = vi.spyOn(settingsApi, 'signoffSetting')
    renderWithApi(<SettingsScreen />, { fetch: server() })
    await loaded()

    const pda = card(/pda threshold/i)
    fireEvent.click(within(pda).getByRole('button', { name: /sign off/i }))

    await waitFor(() => expect(within(pda).getByText('5.5%')).toBeInTheDocument())
    expect(signoff).toHaveBeenCalledWith({ field: 'pda_threshold' }, 'a.sharma')
    expect(pda).not.toHaveClass('is-pending')
    expect(within(pda).getByRole('button', { name: /edit/i })).toBeInTheDocument()
  })

  test('the proposer sees no sign-off action on their own change', async () => {
    renderWithApi(<SettingsScreen />, { fetch: server(), session: R_MEHTA })
    await loaded()

    const pda = card(/pda threshold/i)
    expect(within(pda).queryByRole('button', { name: /sign off/i })).not.toBeInTheDocument()
    expect(
      within(pda).getByText(/needs a second sign-off from a different account/i),
    ).toBeInTheDocument()
  })

  test('a server rejection is shown on the card it belongs to', async () => {
    vi.spyOn(settingsApi, 'signoffSetting').mockRejectedValue(
      new ApiError(403, ['The second sign-off has to come from a different account.']),
    )
    renderWithApi(<SettingsScreen />, { fetch: server() })
    await loaded()

    const pda = card(/pda threshold/i)
    fireEvent.click(within(pda).getByRole('button', { name: /sign off/i }))
    expect(
      await within(pda).findByText('The second sign-off has to come from a different account.'),
    ).toBeInTheDocument()
    expect(within(pda).getByText('5.0%')).toBeInTheDocument()
  })

  test('corrective status shows the live FN rate, with the FP rate for context only', async () => {
    renderWithApi(<SettingsScreen />, { fetch: server() })
    const status = await screen.findByRole('region', { name: /corrective feedback status/i })

    await within(status).findByText('2.8%')
    expect(status.querySelector('.corrective-rate')).toHaveTextContent(
      'FN rate 2.8% (N=14 confirmed outcomes)',
    )
    expect(status.querySelector('.corrective-context')).toHaveTextContent(
      'FP rate 11.4%, shown for context only, never a trigger.',
    )
    const current = within(status).getByText('OK', { selector: '.corrective-current' })
    expect(current).toHaveClass('badge-pass')
  })

  test.each([
    ['CEILING_EXCEEDED', 'badge-reject', /above the 5\.0% ceiling/i],
    ['INSUFFICIENT_DATA', 'badge-watch', /fewer than 10 confirmed outcomes/i],
  ] as const)('corrective status %s', async (status, badge, note) => {
    vi.spyOn(settingsApi, 'getCorrectiveStatus').mockResolvedValue({
      fn_rate: 0.08,
      fp_rate: 0.1,
      confirmed_outcome_count: status === 'INSUFFICIENT_DATA' ? 4 : 20,
      status,
    })
    renderWithApi(<SettingsScreen />, { fetch: server() })
    const region = await screen.findByRole('region', { name: /corrective feedback status/i })

    const current = await within(region).findByText(status.replace('_', ' '), {
      selector: '.corrective-current',
    })
    expect(current).toHaveClass(badge)
    expect(await within(region).findByText(note)).toBeInTheDocument()
  })

  test('the worklist lists dispositions awaiting a confirmed outcome, with days pending', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-09-27T14:00:00Z'))
    renderWithApi(<SettingsScreen />, { fetch: server() })
    const worklist = await screen.findByRole('region', { name: /worklist/i })

    const link = await within(worklist).findByRole('link', { name: 'DUT-042' })
    expect(link).toHaveAttribute('href', '/parts/DUT-042')
    const row = link.closest('tr')!
    await within(row).findByText('LOT-2024-8841')
    expect(within(row).getByText('REJECT')).toBeInTheDocument()
    expect(within(row).getByText('12d')).toBeInTheDocument()
    expect(within(worklist).getAllByRole('row')).toHaveLength(5)
  })

  test('an empty worklist says so', async () => {
    vi.spyOn(settingsApi, 'getWorklist').mockResolvedValue({ pending: [] })
    renderWithApi(<SettingsScreen />, { fetch: server() })
    expect(await screen.findByText(/no dispositions are awaiting/i)).toBeInTheDocument()
  })

  test('a failed settings load shows the error and can be retried', async () => {
    vi.spyOn(settingsApi, 'getSettings').mockRejectedValueOnce(
      new ApiError(500, ['settings store unavailable']),
    )
    renderWithApi(<SettingsScreen />, { fetch: server() })

    expect(await screen.findByText('settings store unavailable')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    await loaded()
  })
})
