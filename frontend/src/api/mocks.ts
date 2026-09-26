/**
 * Hand-typed stand-ins for routes that are in IMPLEMENTATION_PLAN.md Part 5.6 but not yet in the
 * live OpenAPI schema. Each MOCK_<TypeName> mirrors its contracts.py Pydantic model field for
 * field, and each has an open BLOCKERS.md entry naming the route it stands in for.
 *
 * When a route goes live, the one function that calls its mock (src/api/auth.ts for login) is
 * edited to call the generated client, and the mock is deleted here. There is no global
 * mock switch on purpose.
 */
import { ApiError } from './errors'

/** contracts.py `LoginRequest`. Stands in for `POST /auth/login`'s body (P5.4). */
export interface MOCK_LoginRequest {
  account_id: string
  pin: string
}

/** contracts.py `TokenResponse`. Stands in for `POST /auth/login`'s response (P5.4). */
export interface MOCK_TokenResponse {
  access_token: string
  token_type: 'bearer'
  account_id: string
  role: string
}

/**
 * Demo PINs, read from scripts/seed.py (the same values `seed.py` hashes into the database). They
 * are only here so the mock can reject a wrong PIN and the error state is exercisable. The real
 * check is argon2 on the server (P5.4), and this table is deleted along with the mock.
 */
const MOCK_SEEDED_PINS: Record<string, { pin: string; role: string }> = {
  'a.sharma': { pin: '1234', role: 'Quality Engineer' },
  'r.mehta': { pin: '5678', role: 'Reliability Engineer' },
}

/** Simulated network latency, so loading states render the way they will against the real route. */
const MOCK_LATENCY_MS = 250

/**
 * Behaves like `POST /auth/login` will: a TokenResponse on a matching PIN, a 401 otherwise.
 * The token is not a JWT, only an opaque placeholder. Today's real ingestion routes don't
 * verify it yet (they take `account_id` as a form field until identity/ lands).
 */
export async function MOCK_login(
  request: MOCK_LoginRequest,
  latencyMs = MOCK_LATENCY_MS,
): Promise<MOCK_TokenResponse> {
  await new Promise((resolve) => setTimeout(resolve, latencyMs))
  const account = Object.hasOwn(MOCK_SEEDED_PINS, request.account_id)
    ? MOCK_SEEDED_PINS[request.account_id]
    : undefined
  if (!account || account.pin !== request.pin) {
    throw new ApiError(401, ['Incorrect PIN for this account.'])
  }
  return {
    access_token: `mock-token.${request.account_id}`,
    token_type: 'bearer',
    account_id: request.account_id,
    role: account.role,
  }
}
