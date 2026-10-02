// @vitest-environment node
import { describe, expect, test, vi } from 'vitest'
import { login } from './auth'
import { createApiClient } from './client'
import { ApiError } from './errors'

const BASE = 'http://api.test'

function fakeServer(status: number, body: unknown) {
  const requests: Request[] = []
  const fetch = vi.fn(async (input: Request) => {
    requests.push(input)
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  const client = createApiClient({ baseUrl: BASE, getToken: () => null, fetch })
  return { client, requests }
}

describe('login (POST /auth/login, real route)', () => {
  test('sends the account id and PIN, and returns the bearer TokenResponse', async () => {
    const { client, requests } = fakeServer(200, {
      access_token: 'jwt.r.mehta',
      token_type: 'bearer',
      account_id: 'r.mehta',
      role: 'Reliability Engineer',
    })

    const result = await login(client, { account_id: 'r.mehta', pin: '5678' })

    expect(result).toEqual({
      access_token: 'jwt.r.mehta',
      token_type: 'bearer',
      account_id: 'r.mehta',
      role: 'Reliability Engineer',
    })
    const [request] = requests
    expect(request.method).toBe('POST')
    expect(request.url).toBe(`${BASE}/auth/login`)
    expect(await request.json()).toEqual({ account_id: 'r.mehta', pin: '5678' })
  })

  test('a wrong PIN surfaces the server message as a 401 ApiError', async () => {
    const { client } = fakeServer(401, { detail: 'Incorrect PIN for this account.' })
    const error = await login(client, { account_id: 'a.sharma', pin: '0000' }).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(401)
    expect(error.messages).toEqual(['Incorrect PIN for this account.'])
  })
})
