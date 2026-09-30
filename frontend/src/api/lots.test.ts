// @vitest-environment node
// Node, not jsdom: jsdom's File doesn't serialize through Node's Request, so multipart bodies
// would arrive empty. Here FormData/File/Request are all one implementation, as in a browser.
import { describe, expect, test, vi } from 'vitest'
import { createApiClient } from './client'
import { ApiError, describeFailure, errorMessages } from './errors'
import {
  ensureReadable,
  listProjects,
  loadDemoLot,
  lotIdProblem,
  uploadCheckpoint,
  uploadLot,
  type LotMetadata,
} from './lots'

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
  const client = createApiClient({ baseUrl: BASE, getToken: () => 'tok', fetch })
  return { client, requests }
}

const UPLOADED = {
  lot_id: 'LOT-1',
  part_number: 'PN-1',
  status: 'IN_PROGRESS',
  reading_count: 12,
  insufficient_data_components: [],
}

const META: LotMetadata = {
  lot_id: 'LOT-1',
  part_number: 'PN-1',
  manufacturer: 'ACME',
  date_code: '2418',
  test_date: '2024-05-12',
}

const csv = (name = 'lot.csv') =>
  new File(['component_id,checkpoint_hour,iddq_uA\nC1,0,10\n'], name, { type: 'text/csv' })

describe('uploadLot (POST /lots, real route)', () => {
  test('sends the file and every metadata field as multipart, attributed to the account', async () => {
    const { client, requests } = fakeServer(200, UPLOADED)

    const result = await uploadLot(client, META, csv('my lot.csv'), 'a.sharma')

    expect(result).toEqual(UPLOADED)
    const [request] = requests
    expect(request.method).toBe('POST')
    expect(request.url).toBe(`${BASE}/lots`)
    expect(request.headers.get('Content-Type')).toMatch(/^multipart\/form-data; boundary=/)
    expect(request.headers.get('Authorization')).toBe('Bearer tok')
    const form = await request.formData()
    expect(Object.fromEntries([...form.entries()].filter(([k]) => k !== 'file'))).toEqual({
      ...META,
      account_id: 'a.sharma',
    })
    const file = form.get('file') as File
    expect(file.name).toBe('my lot.csv')
    expect(await file.text()).toContain('iddq_uA')
  })

  test('a 409 (lot already exists) surfaces the server message', async () => {
    const { client } = fakeServer(409, { detail: "lot 'LOT-1' already exists" })
    const error = await uploadLot(client, META, csv(), 'a.sharma').catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(409)
    expect(error.messages).toEqual(["lot 'LOT-1' already exists"])
  })

  test('a 422 from ingestion keeps every validation message, not just the first', async () => {
    const detail = ['line 3: value "x" is not a number', 'line 4: component_id is empty']
    const { client } = fakeServer(422, { detail })
    const error = await uploadLot(client, META, csv(), 'a.sharma').catch((e) => e)
    expect(error.messages).toEqual(detail)
  })
})

describe('uploadCheckpoint (POST /lots/{lot_id}/checkpoints, real route)', () => {
  test('targets the lot by id (escaped) and sends only file + account', async () => {
    const { client, requests } = fakeServer(200, { ...UPLOADED, status: 'COMPLETE' })

    const result = await uploadCheckpoint(client, 'LOT 1/A', csv('168h.csv'), 'r.mehta')

    expect(result.status).toBe('COMPLETE')
    expect(requests[0].url).toBe(`${BASE}/lots/LOT%201%2FA/checkpoints`)
    const form = await requests[0].formData()
    expect([...form.keys()].sort()).toEqual(['account_id', 'file'])
    expect(form.get('account_id')).toBe('r.mehta')
  })

  test('a 404 (no such lot) surfaces the server message', async () => {
    const { client } = fakeServer(404, { detail: "lot 'X' not found" })
    await expect(uploadCheckpoint(client, 'X', csv(), 'a.sharma')).rejects.toMatchObject({
      status: 404,
      messages: ["lot 'X' not found"],
    })
  })
})

describe('loadDemoLot (POST /lots/demo, real route)', () => {
  test('posts the account as a urlencoded form, as the schema declares', async () => {
    const { client, requests } = fakeServer(200, { ...UPLOADED, lot_id: 'demo-1a2b3c4d' })

    const result = await loadDemoLot(client, 'a.sharma')

    expect(result.lot_id).toBe('demo-1a2b3c4d')
    expect(requests[0].headers.get('Content-Type')).toBe('application/x-www-form-urlencoded')
    expect(await requests[0].text()).toBe('account_id=a.sharma')
  })
})

describe('listProjects (GET /projects, real route)', () => {
  test('returns projects newest first', async () => {
    const project = (id: string, created_at: string) => ({
      project_id: id,
      lot_id: id,
      part_number: 'PN',
      created_at,
      created_by: 'a.sharma',
    })
    const { client } = fakeServer(200, [
      project('old', '2026-09-20T10:00:00'),
      project('new', '2026-09-26T09:00:00'),
      project('mid', '2026-09-24T12:00:00'),
    ])
    expect((await listProjects(client)).map((p) => p.project_id)).toEqual(['new', 'mid', 'old'])
  })

  test('a server error becomes an ApiError, not an empty list', async () => {
    const { client } = fakeServer(500, {})
    await expect(listProjects(client)).rejects.toBeInstanceOf(ApiError)
  })
})

describe('errorMessages', () => {
  test("FastAPI's own validation items read as location: message", () => {
    const body = {
      detail: [{ loc: ['body', 'lot_id'], msg: 'Field required', type: 'missing' }],
    }
    expect(errorMessages(body, 422)).toEqual(['lot_id: Field required'])
  })

  test.each([[null], [{}], [{ detail: '' }], [{ detail: [] }], ['<html>oops</html>']])(
    'a body with no usable detail (%j) still yields one readable line',
    (body) => {
      expect(errorMessages(body, 502)).toEqual(['The server answered 502 with no further detail.'])
    },
  )

  test('describeFailure explains a missing response instead of showing "Failed to fetch"', () => {
    expect(describeFailure(new TypeError('Failed to fetch'))).toEqual([
      'No readable response from the API server. Check that the backend is running; if it is, its log shows the error.',
    ])
  })
})

describe('lotIdProblem: ids the API could store but never address again', () => {
  test.each(['LOT-2024-8841', 'lot 7', 'A.B', '..A', 'x#y', '100%', 'Ünïcødé'])(
    '%j is fine',
    (id) => expect(lotIdProblem(id)).toBeNull(),
  )

  test.each(['A/B', '/', 'LOT/2024/01'])('%j is refused: a slash splits the URL path', (id) => {
    expect(lotIdProblem(id)).toMatch(/can't contain/)
  })

  test.each(['.', '..', '...'])('%j is refused: dot segments collapse in a URL', (id) => {
    expect(lotIdProblem(id)).toMatch(/only dots/)
  })
})

describe('ensureReadable: a staged file that changed on disk is caught before sending', () => {
  test('a readable file passes', async () => {
    await expect(ensureReadable(new File(['a,b'], 'ok.csv'))).resolves.toBeUndefined()
  })

  test('an unreadable file becomes a message naming it', async () => {
    const file = new File(['a,b'], 'gone.csv')
    file.slice = () => {
      throw new DOMException('changed', 'NotReadableError')
    }
    await expect(ensureReadable(file)).rejects.toMatchObject({
      messages: ['gone.csv changed or was removed after you chose it. Choose it again.'],
    })
  })
})

describe('non-JSON success bodies', () => {
  test('an HTML page where JSON was expected is explained, not a raw SyntaxError', async () => {
    const fetch = vi.fn(async () => new Response('<!doctype html><html></html>', { status: 200 }))
    const client = createApiClient({ baseUrl: BASE, getToken: () => null, fetch })
    const error = await listProjects(client).catch((e) => e)
    expect(describeFailure(error)).toEqual([
      "The server's response wasn't valid JSON. Check that VITE_API_BASE_URL points at the API.",
    ])
  })
})

describe('listProjects ordering', () => {
  test('equal timestamps keep a stable, locale-independent order', async () => {
    const p = (id: string, created_at: string) => ({
      project_id: id,
      lot_id: id,
      part_number: 'PN',
      created_at,
      created_by: 'a.sharma',
    })
    const { client } = fakeServer(200, [
      p('b', '2026-09-26T09:00:00'),
      p('a', '2026-09-26T09:00:00'),
      p('c', '2026-09-26T10:00:00'),
    ])
    expect((await listProjects(client)).map((x) => x.project_id)).toEqual(['c', 'b', 'a'])
  })
})

