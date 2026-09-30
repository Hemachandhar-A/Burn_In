import type { ApiClient } from './client'
import { unwrap } from './errors'
import type { components } from './schema'

export type LoginRequest = components['schemas']['LoginRequest']
export type TokenResponse = components['schemas']['TokenResponse']

/** `POST /auth/login`: real (P5.4, identity/router.py). */
export async function login(client: ApiClient, request: LoginRequest): Promise<TokenResponse> {
  return unwrap(await client.POST('/auth/login', { body: request }))
}
