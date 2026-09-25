import { describe, expect, test, vi } from 'vitest'
import { createApiClient, DEFAULT_API_BASE_URL, resolveApiBaseUrl } from './client'

function recordingFetch() {
  const requests: Request[] = []
  const fetch = vi.fn(async (input: Request) => {
    requests.push(input)
    return new Response(JSON.stringify({ status: 'ok' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  return { fetch, requests }
}

describe('resolveApiBaseUrl', () => {
  test('falls back to the local uvicorn origin when VITE_API_BASE_URL is unset', () => {
    expect(resolveApiBaseUrl({})).toBe(DEFAULT_API_BASE_URL)
    expect(DEFAULT_API_BASE_URL).toBe('http://localhost:8000')
  })

  test('uses VITE_API_BASE_URL when set, without a trailing slash', () => {
    expect(resolveApiBaseUrl({ VITE_API_BASE_URL: 'http://10.0.0.5:9000/' })).toBe(
      'http://10.0.0.5:9000',
    )
  })

  test('an explicit empty value means same-origin (the single-process demo build)', () => {
    expect(resolveApiBaseUrl({ VITE_API_BASE_URL: '' })).toBe('')
  })
})

describe('createApiClient', () => {
  test('sends requests to the configured base URL', async () => {
    const { fetch, requests } = recordingFetch()
    const client = createApiClient({ baseUrl: 'http://api.test', getToken: () => null, fetch })

    const { data } = await client.GET('/health')

    expect(data).toEqual({ status: 'ok' })
    expect(requests[0].url).toBe('http://api.test/health')
  })

  test('attaches the in-memory JWT as a bearer token when signed in', async () => {
    const { fetch, requests } = recordingFetch()
    const client = createApiClient({ baseUrl: 'http://api.test', getToken: () => 'jwt-abc', fetch })

    await client.GET('/health')

    expect(requests[0].headers.get('Authorization')).toBe('Bearer jwt-abc')
  })

  test('sends no Authorization header when signed out', async () => {
    const { fetch, requests } = recordingFetch()
    const client = createApiClient({ baseUrl: 'http://api.test', getToken: () => null, fetch })

    await client.GET('/health')

    expect(requests[0].headers.has('Authorization')).toBe(false)
  })

  test('reads the token per request, so a sign-in after creation takes effect', async () => {
    const { fetch, requests } = recordingFetch()
    let token: string | null = null
    const client = createApiClient({ baseUrl: 'http://api.test', getToken: () => token, fetch })

    await client.GET('/health')
    token = 'jwt-later'
    await client.GET('/health')

    expect(requests[0].headers.has('Authorization')).toBe(false)
    expect(requests[1].headers.get('Authorization')).toBe('Bearer jwt-later')
  })
})
