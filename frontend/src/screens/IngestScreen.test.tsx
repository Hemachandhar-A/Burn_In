import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, test } from 'vitest'
import { fakeServer, renderWithApi, type Routes } from '../test-utils'
import { IngestScreen } from './IngestScreen'

const PROJECTS = [
  {
    project_id: 'p-1',
    lot_id: 'LOT-2024-7712',
    part_number: 'LM117-HV',
    created_at: '2026-09-25T09:15:00',
    created_by: 'r.mehta',
  },
  {
    project_id: 'p-2',
    lot_id: 'LOT-2024-8841',
    part_number: 'AD590-JH',
    created_at: '2026-09-26T14:32:10',
    created_by: 'a.sharma',
  },
]

const uploaded = (overrides: Record<string, unknown> = {}) => ({
  lot_id: 'LOT-9',
  part_number: 'PN-9',
  status: 'IN_PROGRESS',
  reading_count: 231,
  insufficient_data_components: [],
  ...overrides,
})

function setup(routes: Routes = {}) {
  const server = fakeServer({ 'GET /projects': { body: PROJECTS }, ...routes })
  const view = renderWithApi(<IngestScreen />, { fetch: server.fetch })
  return { ...server, ...view }
}

const csv = (name = 'lot.csv', content = 'component_id,checkpoint_hour,iddq_uA\nC1,0,10\n') =>
  new File([content], name, { type: 'text/csv' })

const lotInput = () => screen.getByLabelText(/lot csv file/i)
const checkpointInput = () => screen.getByLabelText(/checkpoint csv file/i)
const commit = () => screen.getByRole('button', { name: /commit batch|committing/i })
const demo = () => screen.getByRole('button', { name: /load demo lot|loading demo/i })

function choose(input: HTMLElement, file: File) {
  fireEvent.change(input, { target: { files: [file] } })
}

function fillMetadata(values: Partial<Record<string, string>> = {}) {
  const v = {
    'Lot ID': 'LOT-9',
    'Part Number': 'PN-9',
    Manufacturer: 'Analog Devices',
    'Date Code': '2418',
    'Test Date': '2024-05-12',
    ...values,
  }
  for (const [label, value] of Object.entries(v)) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } })
  }
}

const posts = (requests: Request[]) => requests.filter((r) => r.method === 'POST')

describe('Ingest screen (E6 screen 2, E7)', () => {
  test('has the upload, checkpoint, metadata and recent-ingestions sections', async () => {
    setup()
    expect(screen.getByRole('heading', { level: 1, name: 'Ingest' })).toBeInTheDocument()
    for (const name of [
      'Upload Lot CSV',
      'Add Checkpoint Reading',
      'Lot Metadata',
      'Recent Ingestions',
    ]) {
      expect(screen.getByRole('heading', { name })).toBeInTheDocument()
    }
    for (const label of ['Lot ID', 'Part Number', 'Manufacturer', 'Date Code', 'Test Date']) {
      expect(screen.getByLabelText(label)).toBeInTheDocument()
    }
    expect(screen.getByLabelText('Test Date')).toHaveAttribute('type', 'date')
    await screen.findByText('LOT-2024-8841')
  })

  test('recent ingestions come from GET /projects, newest first, linking to each lot', async () => {
    setup()
    const table = await screen.findByRole('table', { name: 'Recent Ingestions' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((r) => within(r).getAllByRole('cell')[0].textContent)).toEqual([
      'LOT-2024-8841',
      'LOT-2024-7712',
    ])
    expect(within(rows[0]).getByText('2026-09-26 14:32')).toBeInTheDocument()
    expect(within(rows[0]).getByRole('link', { name: 'LOT-2024-8841' })).toHaveAttribute(
      'href',
      '/lots/LOT-2024-8841',
    )
    expect(screen.getByText('2 lots on record')).toBeInTheDocument()
  })

  test('no projects yet shows an empty state, not an empty table', async () => {
    setup({ 'GET /projects': { body: [] } })
    expect(await screen.findByText('No lots on record yet.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.queryByText(/lots? on record$/)).toBeNull()
  })

  test('a failed GET /projects is shown with a retry, not as an empty list', async () => {
    let calls = 0
    setup({
      'GET /projects': () => (++calls === 1 ? { status: 500, body: {} } : { body: PROJECTS }),
    })
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Could not load recent ingestions')
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('LOT-2024-8841')).toBeInTheDocument()
  })

  test('Commit Batch with nothing staged says what to do, and sends nothing', async () => {
    const { requests } = setup()
    fireEvent.click(commit())
    expect(
      await screen.findByText('Choose a lot CSV or a checkpoint CSV first.'),
    ).toBeInTheDocument()
    expect(posts(requests)).toHaveLength(0)
  })

  test('a new lot needs every metadata field; missing ones are named at the field', async () => {
    const { requests } = setup()
    choose(lotInput(), csv())
    fillMetadata({ Manufacturer: '', 'Test Date': '' })
    fireEvent.click(commit())

    expect(screen.getByLabelText('Manufacturer')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Manufacturer')).toHaveAccessibleDescription(
      'Required for a new lot.',
    )
    expect(screen.getByLabelText('Test Date')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Lot ID')).toHaveAttribute('aria-invalid', 'false')
    expect(posts(requests)).toHaveLength(0)
  })

  test.each([
    ['readings.xlsx', 'x', 'readings.xlsx is not a .csv file.'],
    ['empty.csv', '', 'empty.csv is empty.'],
  ])('%s is refused at selection', (name, content, message) => {
    setup()
    choose(lotInput(), csv(name, content))
    expect(screen.getByText(message)).toBeInTheDocument()
    expect(screen.queryByText(`Selected: ${name}`)).toBeNull()
  })

  test('a new lot posts its CSV and metadata, attributed to the signed-in account', async () => {
    const { requests } = setup({ 'POST /lots': { body: uploaded() } })
    choose(lotInput(), csv('lot-9.csv'))
    expect(screen.getByText('lot-9.csv')).toBeInTheDocument()
    fillMetadata()

    fireEvent.click(commit())

    const result = await screen.findByRole('region', { name: 'Ingestion result' })
    const [post] = posts(requests)
    expect(new URL(post.url).pathname).toBe('/lots')
    const form = await post.formData()
    expect(form.get('lot_id')).toBe('LOT-9')
    expect(form.get('manufacturer')).toBe('Analog Devices')
    expect(form.get('test_date')).toBe('2024-05-12')
    expect(form.get('account_id')).toBe('a.sharma')
    expect(form.has('file')).toBe(true)

    // Status is the backend's word, verbatim (rule 10).
    expect(within(result).getByText('IN_PROGRESS')).toBeInTheDocument()
    expect(within(result).getByText('231')).toBeInTheDocument()
    expect(within(result).getByRole('link', { name: /open lot dashboard/i })).toHaveAttribute(
      'href',
      '/lots/LOT-9',
    )
    expect(screen.queryByText('lot-9.csv')).toBeNull()
  })

  test('components with no 0h/24h reading are listed, never dropped silently (rule 7)', async () => {
    setup({ 'POST /lots': { body: uploaded({ insufficient_data_components: ['C07', 'C19'] }) } })
    choose(lotInput(), csv())
    fillMetadata()
    fireEvent.click(commit())

    const result = await screen.findByRole('region', { name: 'Ingestion result' })
    expect(result).toHaveTextContent('2 components have no 0h or 24h reading')
    expect(within(result).getByText('C07, C19')).toBeInTheDocument()
  })

  test('a rejected file shows every validation message the server gave', async () => {
    const detail = ['line 3: value "x" is not a number', 'line 7: component_id is empty']
    setup({ 'POST /lots': { status: 422, body: { detail } } })
    choose(lotInput(), csv())
    fillMetadata()
    fireEvent.click(commit())

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Lot upload failed')
    for (const line of detail) expect(within(alert).getByText(line)).toBeInTheDocument()
    // Kept staged, so fixing metadata and retrying doesn't mean re-choosing the file.
    expect(screen.getByText('lot.csv')).toBeInTheDocument()
  })

  test('a checkpoint alone needs only the Lot ID, and merges into that lot', async () => {
    const { requests } = setup({
      'POST /lots/LOT%201/checkpoints': { body: uploaded({ lot_id: 'LOT 1', status: 'COMPLETE' }) },
    })
    choose(checkpointInput(), csv('168h.csv'))
    expect(screen.getByText('168h.csv')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Lot ID'), { target: { value: 'LOT 1' } })

    fireEvent.click(commit())

    const result = await screen.findByRole('region', { name: 'Ingestion result' })
    expect(within(result).getByText('COMPLETE')).toBeInTheDocument()
    const [post] = posts(requests)
    expect(post.url).toBe('http://api.test/lots/LOT%201/checkpoints')
    expect((await post.formData()).get('account_id')).toBe('a.sharma')
  })

  test('a checkpoint with no Lot ID is caught before sending', () => {
    const { requests } = setup()
    choose(checkpointInput(), csv())
    fireEvent.click(commit())
    expect(screen.getByLabelText('Lot ID')).toHaveAccessibleDescription(
      'Required: the checkpoint merges into this lot.',
    )
    expect(posts(requests)).toHaveLength(0)
  })

  test('lot then checkpoint in one batch: the checkpoint is sent only after the lot exists', async () => {
    const order: string[] = []
    setup({
      'POST /lots': () => (order.push('lot'), { body: uploaded() }),
      'POST /lots/LOT-9/checkpoints': () => (
        order.push('checkpoint'),
        { body: uploaded({ reading_count: 300 }) }
      ),
    })
    choose(lotInput(), csv())
    choose(checkpointInput(), csv('96h.csv'))
    fillMetadata()
    fireEvent.click(commit())

    const result = await screen.findByRole('region', { name: 'Ingestion result' })
    await waitFor(() => expect(within(result).getByText('300')).toBeInTheDocument())
    expect(order).toEqual(['lot', 'checkpoint'])
  })

  test('if the lot upload fails, the staged checkpoint is not sent', async () => {
    const { requests } = setup({ 'POST /lots': { status: 409, body: { detail: 'exists' } } })
    choose(lotInput(), csv())
    choose(checkpointInput(), csv('96h.csv'))
    fillMetadata()
    fireEvent.click(commit())

    await screen.findByRole('alert')
    expect(posts(requests)).toHaveLength(1)
    expect(screen.getByText('96h.csv')).toBeInTheDocument()
  })

  test('Load Demo Lot posts the account and shows the generated lot', async () => {
    const { requests } = setup({
      'POST /lots/demo': { body: uploaded({ lot_id: 'demo-1a2b3c4d', part_number: 'DEMO-PN' }) },
    })
    fireEvent.click(demo())

    const result = await screen.findByRole('region', { name: 'Ingestion result' })
    expect(within(result).getByText('demo-1a2b3c4d')).toBeInTheDocument()
    expect(await posts(requests)[0].text()).toBe('account_id=a.sharma')
  })

  test('while a request is in flight both actions are disabled', async () => {
    let release: () => void = () => {}
    setup({
      'POST /lots/demo': () =>
        new Promise((resolve) => (release = () => resolve({ body: uploaded() }))),
    })
    fireEvent.click(demo())
    await waitFor(() => expect(demo()).toBeDisabled())
    expect(commit()).toBeDisabled()
    await act(async () => release())
    await waitFor(() => expect(demo()).toBeEnabled())
  })

  test('a successful ingest refreshes the recent-ingestions list', async () => {
    let listed = PROJECTS.slice(0, 1)
    setup({
      'GET /projects': () => ({ body: listed }),
      'POST /lots/demo': () => {
        listed = PROJECTS
        return { body: uploaded() }
      },
    })
    await screen.findByText('LOT-2024-7712')
    fireEvent.click(demo())
    expect(await screen.findByText('LOT-2024-8841')).toBeInTheDocument()
  })
})
