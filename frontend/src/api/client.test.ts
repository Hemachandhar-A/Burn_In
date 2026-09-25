import { describe, expect, test, vi } from 'vitest'
import { createApiClient, DEFAULT_API_BASE_URL, resolveApiBaseUrl } from './client'

function recordingFetch(status = 200) {
  const requests: Request[] = []
  const fetch = vi.fn(async (input: Request) => {
    requests.push(input)
    return new Response(JSON.stringify({ status: status === 200 ? 'ok' : 'nope' }), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  return { fetch, requests }
}

const ORIGIN = 'http://demo.host:8000'

describe('resolveApiBaseUrl', () => {
  test('dev server, unset -> the local uvicorn origin', () => {
    expect(resolveApiBaseUrl({ DEV: true }, ORIGIN)).toBe(DEFAULT_API_BASE_URL)
    expect(DEFAULT_API_BASE_URL).toBe('http://localhost:8000')
  })

  test('production build, unset -> same-origin (FastAPI serves the build, Part 5.6)', () => {
    expect(resolveApiBaseUrl({ DEV: false }, ORIGIN)).toBe(ORIGIN)
  })

  test('uses an explicit absolute URL, without trailing slashes', () => {
    expect(resolveApiBaseUrl({ VITE_API_BASE_URL: 'http://10.0.0.5:9000///', DEV: true })).toBe(
      'http://10.0.0.5:9000',
    )
  })

  test('accepts https and keeps a path prefix', () => {
    expect(resolveApiBaseUrl({ VITE_API_BASE_URL: 'https://api.test/v1/', DEV: true })).toBe(
      'https://api.test/v1',
    )
  })

  test('ignores surrounding whitespace (a stray space in .env.local)', () => {
    expect(resolveApiBaseUrl({ VITE_API_BASE_URL: '  http://x.test:1/  ', DEV: true })).toBe(
      'http://x.test:1',
    )
  })

  test.each(['', '   '])('an empty value (%j) means same-origin, in dev too', (value) => {
    expect(resolveApiBaseUrl({ VITE_API_BASE_URL: value, DEV: true }, ORIGIN)).toBe(ORIGIN)
  })

  test('a bare path prefix means same-origin under that prefix', () => {
    expect(resolveApiBaseUrl({ VITE_API_BASE_URL: '/api/', DEV: true }, ORIGIN)).toBe(
      `${ORIGIN}/api`,
    )
  })

  test.each([
    'localhost:8000', // no scheme: would silently become a relative path
    'api.example.com',
    'ftp://files.test',
    '//other.host', // protocol-relative: ambiguous, reject rather than guess
    'http://x.test?debug=1',
    'http://x.test#frag',
    '/api?x=1',
    'not a url',
  ])('rejects %j with an error that names the variable', (value) => {
    expect(() => resolveApiBaseUrl({ VITE_API_BASE_URL: value, DEV: true }, ORIGIN)).toThrow(
      /VITE_API_BASE_URL/,
    )
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

  test('keeps a base-URL path prefix in front of every route', async () => {
    const { fetch, requests } = recordingFetch()
    const client = createApiClient({ baseUrl: 'http://api.test/v1', getToken: () => null, fetch })

    await client.GET('/health')

    expect(requests[0].url).toBe('http://api.test/v1/health')
  })

  test('attaches the in-memory JWT as a bearer token when signed in', async () => {
    const { fetch, requests } = recordingFetch()
    const client = createApiClient({ baseUrl: 'http://api.test', getToken: () => 'jwt-abc', fetch })

    await client.GET('/health')

    expect(requests[0].headers.get('Authorization')).toBe('Bearer jwt-abc')
  })

  test.each([null, ''])('sends no Authorization header when the token is %j', async (token) => {
    const { fetch, requests } = recordingFetch()
    const client = createApiClient({ baseUrl: 'http://api.test', getToken: () => token, fetch })

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

  test('a 401 on an authenticated request reports the token that was rejected', async () => {
    const { fetch } = recordingFetch(401)
    const onUnauthorized = vi.fn()
    const client = createApiClient({
      baseUrl: 'http://api.test',
      getToken: () => 'jwt-expired',
      fetch,
      onUnauthorized,
    })

    const { response } = await client.GET('/health')

    expect(onUnauthorized).toHaveBeenCalledExactlyOnceWith('jwt-expired')
    expect(response.status).toBe(401) // still surfaced to the caller, not swallowed
  })

  test('reports the token the request carried, even if the session changed mid-flight', async () => {
    let token: string | null = 'jwt-old'
    const onUnauthorized = vi.fn()
    const fetch = vi.fn(async () => {
      token = 'jwt-new' // a re-login lands while the old request is still in flight
      return new Response('{}', { status: 401, headers: { 'Content-Type': 'application/json' } })
    })
    const client = createApiClient({
      baseUrl: 'http://api.test',
      getToken: () => token,
      fetch,
      onUnauthorized,
    })

    await client.GET('/health')

    expect(onUnauthorized).toHaveBeenCalledExactlyOnceWith('jwt-old')
  })

  test('a 401 on an anonymous request (e.g. a wrong PIN) is not a session expiry', async () => {
    const { fetch } = recordingFetch(401)
    const onUnauthorized = vi.fn()
    const client = createApiClient({
      baseUrl: 'http://api.test',
      getToken: () => null,
      fetch,
      onUnauthorized,
    })

    await client.GET('/health')

    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  test.each([403, 404, 422, 500])('a %i does not end the session', async (status) => {
    const { fetch } = recordingFetch(status)
    const onUnauthorized = vi.fn()
    const client = createApiClient({
      baseUrl: 'http://api.test',
      getToken: () => 'jwt-abc',
      fetch,
      onUnauthorized,
    })

    await client.GET('/health')

    expect(onUnauthorized).not.toHaveBeenCalled()
  })
})
