import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { MOCK_FIXTURE_PROJECTS, MOCK_generateDpaWorkOrder, MOCK_getLotSummary, MOCK_resetStores } from './mocks'

// Every MOCK_ function simulates network latency via a real setTimeout; fake timers let these
// fuzz-style loops (many calls, deliberately) run instantly instead of one real 200ms wait each.
beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

async function fast<T>(promise: Promise<T>): Promise<T> {
  const result = promise
  await vi.advanceTimersByTimeAsync(1000)
  return result
}

describe('MOCK_generateDpaWorkOrder (P1.11 edge-case review)', () => {
  test('never recommends the same component_id twice, across many lots', async () => {
    for (let i = 0; i < 60; i++) {
      const order = await fast(MOCK_generateDpaWorkOrder(`LOT-FUZZ-${i}`))
      const ids = order.recommendations.map((r) => r.component_id)
      expect(new Set(ids).size).toBe(ids.length)
    }
  })

  test("the control-part recommendation is never one of the lot's flagged components", async () => {
    for (let i = 0; i < 60; i++) {
      const lotId = `LOT-FUZZ-${i}`
      const summary = await fast(MOCK_getLotSummary(lotId))
      const flagged = new Set(summary.assessments.map((a) => a.component_id))
      const order = await fast(MOCK_generateDpaWorkOrder(lotId))
      const control = order.recommendations[order.recommendations.length - 1]
      expect(flagged.has(control.component_id)).toBe(false)
    }
  })

  test('is deterministic: the same lot id produces the same recommendations every call', async () => {
    const first = await fast(MOCK_generateDpaWorkOrder('LOT-REPEAT'))
    const second = await fast(MOCK_generateDpaWorkOrder('LOT-REPEAT'))
    expect(second).toEqual(first)
  })

  test('recommends at most 3 parts (E13 step 5)', async () => {
    for (let i = 0; i < 30; i++) {
      const order = await fast(MOCK_generateDpaWorkOrder(`LOT-CAP-${i}`))
      expect(order.recommendations.length).toBeLessThanOrEqual(3)
    }
  })
})

describe('P1.12 mocks: fixture lots (edge-case review)', () => {
  beforeEach(() => {
    MOCK_resetStores()
  })

  test('fixture lots report the status and part number their History events describe', async () => {
    for (const project of MOCK_FIXTURE_PROJECTS) {
      const summary = await fast(MOCK_getLotSummary(project.lot_id))
      expect(summary.part_number).toBe(project.part_number)
    }
    expect((await fast(MOCK_getLotSummary('LOT-2024-9230'))).disposition.status).toBe('IN_PROGRESS')
    expect((await fast(MOCK_getLotSummary('LOT-2024-9104'))).disposition.is_forecast).toBe(true)
    expect((await fast(MOCK_getLotSummary('LOT-2024-8841'))).disposition.status).toBe('COMPLETE')
  })

  test('a lot id that is an Object.prototype key is not mistaken for a fixture', async () => {
    const summary = await fast(MOCK_getLotSummary('constructor'))
    expect(['IN_PROGRESS', 'COMPLETE']).toContain(summary.disposition.status)
    expect(summary.part_number).toMatch(/^AD\d{3}-JH$/)
  })
})
