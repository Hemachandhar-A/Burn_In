import { MOCK_login, type MOCK_LoginRequest, type MOCK_TokenResponse } from './mocks'

/**
 * `POST /auth/login`. MOCKED: the route isn't in the live OpenAPI schema yet (P5.4, BLOCKERS.md).
 * When it lands, regenerate the client and make this take the ApiClient and call
 * `client.POST('/auth/login', { body: request })`. It's the only line that changes.
 */
export function login(request: MOCK_LoginRequest): Promise<MOCK_TokenResponse> {
  return MOCK_login(request)
}
