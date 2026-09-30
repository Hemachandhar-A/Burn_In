/**
 * The two named accounts Login offers (E10 step 1), mirrored from scripts/seed.py.
 *
 * TEMP_ because no route in Part 5.6 lists accounts. `POST /auth/login` itself is real (P5.4);
 * this hand-typed picker is a demo convenience standing in for real account discovery, so Login
 * has each account's id to send as `LoginRequest.account_id` and a display name/role to show
 * before anyone is signed in. Logged in CONTRACT_CHANGES.md (P1.10). Replace this with that
 * route's generated type and a query once an account-listing route exists. Only public fields
 * here, never a PIN.
 */
export interface TEMP_AccountSummary {
  account_id: string
  display_name: string
  role: string
}

export const TEMP_LOGIN_ACCOUNTS: readonly TEMP_AccountSummary[] = [
  { account_id: 'a.sharma', display_name: 'A. Sharma', role: 'Quality Engineer' },
  { account_id: 'r.mehta', display_name: 'R. Mehta', role: 'Reliability Engineer' },
]

/** A signed-in account's display name, falling back to its id (TokenResponse carries no name). */
export function displayNameFor(accountId: string): string {
  return TEMP_LOGIN_ACCOUNTS.find((a) => a.account_id === accountId)?.display_name ?? accountId
}
