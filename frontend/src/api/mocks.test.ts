import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { MOCK_generateDpaWorkOrder, MOCK_getLotSummary, MOCK_getPartDetail } from './mocks'

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

describe('MOCK_getPartDetail (P1.11 edge-case review)', () => {
  test('a part with forecast_unavailable never claims a confidence level for a prediction that does not exist', async () => {
    let sawUnavailable = false
    for (let i = 0; i < 150; i++) {
      const detail = await fast(MOCK_getPartDetail(`DUT-FUZZ-${i}`))
      if (detail.module_b.forecast_unavailable) {
        sawUnavailable = true
        expect(detail.confidence_qualifier).toBe('Not applicable — drift prediction unavailable')
        expect(detail.module_b.predicted_168h).toBeNull()
        expect(detail.module_b.physics_baseline_prediction).toBeNull()
        expect(detail.module_b.physics_disagreement_gap).toBeNull()
      } else {
        expect(detail.confidence_qualifier).not.toBe(
          'Not applicable — drift prediction unavailable',
        )
      }
    }
    // Sanity check the fixture actually exercises the branch under test at all.
    expect(sawUnavailable).toBe(true)
  })

  test('explainable_tags.isolation_forest is never true when isolation_forest_score is null', async () => {
    for (let i = 0; i < 150; i++) {
      const detail = await fast(MOCK_getPartDetail(`DUT-IF-${i}`))
      if (detail.module_a.isolation_forest_score === null) {
        expect(detail.module_a.explainable_tags.isolation_forest).toBe(false)
      }
    }
  })

  test('a severity-cap note only appears alongside a WATCH verdict, never REJECT or PASS', async () => {
    for (let i = 0; i < 150; i++) {
      const detail = await fast(MOCK_getPartDetail(`DUT-CAP-${i}`))
      if (detail.severity_cap_note !== null) {
        expect(detail.verdict).toBe('WATCH')
      }
    }
  })

  test('a worstParameter hint from the Lot Dashboard is honored, so both screens agree', async () => {
    const detail = await fast(
      MOCK_getPartDetail('DUT-777', { worstParameter: 'Propagation Delay' }),
    )
    expect(detail.module_a.parameter).toBe('Propagation Delay')
    expect(detail.module_b.parameter).toBe('Propagation Delay')
    expect(detail.feature_frame.parameter).toBe('Propagation Delay')
  })

  test('an unrecognized worstParameter hint falls back to a normal pick rather than crashing', async () => {
    const detail = await fast(
      MOCK_getPartDetail('DUT-778', { worstParameter: 'Not A Real Parameter' }),
    )
    expect(detail.module_a.parameter).toBeTruthy()
  })

  test('is deterministic: the same component id produces the same detail every call', async () => {
    const first = await fast(MOCK_getPartDetail('DUT-REPEAT'))
    const second = await fast(MOCK_getPartDetail('DUT-REPEAT'))
    expect(second).toEqual(first)
  })

  test('every contribution value is finite and non-negative, never NaN or Infinity', async () => {
    for (let i = 0; i < 60; i++) {
      const detail = await fast(MOCK_getPartDetail(`DUT-FINITE-${i}`))
      expect(detail.mcd_contributions.length).toBeGreaterThan(0)
      expect(detail.ecod_contributions.length).toBeGreaterThan(0)
      for (const row of detail.mcd_contributions) {
        expect(Number.isFinite(row.share_pct)).toBe(true)
        expect(row.share_pct).toBeGreaterThanOrEqual(0)
      }
      for (const row of detail.ecod_contributions) {
        expect(Number.isFinite(row.neg_log_p)).toBe(true)
        expect(row.neg_log_p).toBeGreaterThanOrEqual(0)
      }
    }
  })

  test("synthetic past disposition/confirmed-outcome timestamps don't depend on wall-clock time", async () => {
    const first = await fast(MOCK_getPartDetail('DUT-STABLE-1'))
    const second = await fast(MOCK_getPartDetail('DUT-STABLE-1'))
    expect(second.disposition_history).toEqual(first.disposition_history)
    expect(second.confirmed_outcomes).toEqual(first.confirmed_outcomes)
  })
})
