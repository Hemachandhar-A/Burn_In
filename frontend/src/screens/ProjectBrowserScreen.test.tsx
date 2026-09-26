import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Route, Routes, useParams } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import * as lotDetailApi from '../api/lotDetail'
import type { TEMP_LotSummaryResponse } from '../api/mocks'
import { fakeServer, renderWithApi } from '../test-utils'
import { ProjectBrowserScreen } from './ProjectBrowserScreen'

const PROJECTS = [
  {
    project_id: 'p-1',
    lot_id: 'LOT-B',
    part_number: 'AD590-JH',
    created_at: '2026-09-12T09:00:00',
    created_by: 'a.sharma',
  },
  {
    project_id: 'p-2',
    lot_id: 'LOT-A',
    part_number: 'LM117-HV',
    created_at: '2026-09-14T09:00:00',
    created_by: 'r.mehta',
  },
  {
    project_id: 'p-3',
    lot_id: 'LOT-C',
    part_number: 'DAC8830',
    created_at: '2026-09-10T09:00:00',
    created_by: 'someone.else',
  },
]

function summaryWithStatus(lotId: string, status: 'IN_PROGRESS' | 'COMPLETE') {
  return {
    assessments: [],
    part_number: 'X',
    manufacturer: 'Y',
    lot_size: 77,
    disposition: {
      lot_id: lotId,
      status,
      pda_result: 0,
      verdict: status === 'COMPLETE' ? 'ACCEPT' : 'LOT_ON_TRACK',
      is_forecast: status !== 'COMPLETE',
    },
  } satisfies TEMP_LotSummaryResponse
}

function LotStub() {
  return <p>dashboard for {useParams().lotId}</p>
}

const routed = (
  <Routes>
    <Route path="/" element={<ProjectBrowserScreen />} />
    <Route path="/lots/:lotId" element={<LotStub />} />
  </Routes>
)

function dataRows() {
  return screen.getAllByRole('row').slice(1)
}

function lotOrder() {
  return dataRows().map((row) => within(row).getAllByRole('cell')[0].textContent)
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(lotDetailApi, 'getLotSummary').mockImplementation(async (lotId) =>
    summaryWithStatus(lotId, lotId === 'LOT-A' ? 'IN_PROGRESS' : 'COMPLETE'),
  )
})

describe('ProjectBrowserScreen (E6 screen 5)', () => {
  test('lists every project from the real GET /projects, newest first', async () => {
    const { fetch } = fakeServer({ 'GET /projects': { body: PROJECTS } })
    renderWithApi(routed, { fetch })

    await screen.findByRole('link', { name: 'LOT-A' })
    expect(lotOrder()).toEqual(['LOT-A', 'LOT-B', 'LOT-C'])
    const first = within(dataRows()[0])
    expect(first.getByText('LM117-HV')).toBeInTheDocument()
    expect(first.getByText('2026-09-14')).toBeInTheDocument()
    // created_by is an account id; shown by display name, falling back to the id itself.
    expect(first.getByText('R. Mehta')).toBeInTheDocument()
    expect(within(dataRows()[2]).getByText('someone.else')).toBeInTheDocument()
  })

  test('status comes from each lot summary and is shown as sent, not relabelled', async () => {
    const { fetch } = fakeServer({ 'GET /projects': { body: PROJECTS } })
    renderWithApi(routed, { fetch })

    await waitFor(() => expect(within(dataRows()[0]).getByText('IN PROGRESS')).toBeInTheDocument())
    expect(within(dataRows()[1]).getByText('COMPLETE')).toBeInTheDocument()
  })

  test('a lot whose status could not be loaded says so instead of guessing', async () => {
    vi.spyOn(lotDetailApi, 'getLotSummary').mockRejectedValue(new Error('boom'))
    const { fetch } = fakeServer({ 'GET /projects': { body: PROJECTS.slice(0, 1) } })
    renderWithApi(routed, { fetch })

    expect(await screen.findByText('Unavailable')).toBeInTheDocument()
  })

  test('opening a project goes to its Lot Dashboard', async () => {
    const { fetch } = fakeServer({ 'GET /projects': { body: PROJECTS } })
    renderWithApi(routed, { fetch })

    fireEvent.click(await screen.findByRole('link', { name: 'LOT-B' }))
    expect(await screen.findByText('dashboard for LOT-B')).toBeInTheDocument()
  })

  test('column headers sort, and announce the sort with aria-sort', async () => {
    const { fetch } = fakeServer({ 'GET /projects': { body: PROJECTS } })
    renderWithApi(routed, { fetch })
    await screen.findByRole('link', { name: 'LOT-A' })

    const created = screen.getByRole('columnheader', { name: /created date/i })
    expect(created).toHaveAttribute('aria-sort', 'descending')

    fireEvent.click(screen.getByRole('button', { name: /lot id/i }))
    expect(lotOrder()).toEqual(['LOT-A', 'LOT-B', 'LOT-C'])
    expect(screen.getByRole('columnheader', { name: /lot id/i })).toHaveAttribute(
      'aria-sort',
      'ascending',
    )
    expect(created).not.toHaveAttribute('aria-sort')

    fireEvent.click(screen.getByRole('button', { name: /lot id/i }))
    expect(lotOrder()).toEqual(['LOT-C', 'LOT-B', 'LOT-A'])

    fireEvent.click(screen.getByRole('button', { name: /part number/i }))
    expect(lotOrder()).toEqual(['LOT-B', 'LOT-C', 'LOT-A'])

    await waitFor(() => expect(within(dataRows()[0]).getByText('COMPLETE')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /status/i }))
    expect(lotOrder()[0]).not.toBe('LOT-A')
    fireEvent.click(screen.getByRole('button', { name: /status/i }))
    expect(lotOrder()[0]).toBe('LOT-A')
  })

  test('empty state points to Ingest', async () => {
    const { fetch } = fakeServer({ 'GET /projects': { body: [] } })
    renderWithApi(routed, { fetch })

    expect(await screen.findByText(/no projects on record yet/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /ingest/i })).toHaveAttribute('href', '/ingest')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  test('a failed GET /projects shows the server message and can be retried', async () => {
    let calls = 0
    const { fetch } = fakeServer({
      'GET /projects': () =>
        ++calls === 1
          ? { status: 500, body: { detail: 'database is locked' } }
          : { body: PROJECTS },
    })
    renderWithApi(routed, { fetch })

    expect(await screen.findByText('database is locked')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    expect(await screen.findByRole('link', { name: 'LOT-A' })).toBeInTheDocument()
  })
})
