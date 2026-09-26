import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { ApiError } from './errors'
import {
  MOCK_FIXTURE_PROJECTS,
  MOCK_generateDpaWorkOrder,
  MOCK_getLotSummary,
  MOCK_getPartDetail,
  MOCK_getSettings,
  MOCK_listEvents,
  MOCK_proposeSetting,
  MOCK_resetStores,
  MOCK_signoffSetting,
} from './mocks'

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

describe('P1.12 mocks: settings store and fixture lots (edge-case review)', () => {
  beforeEach(() => {
    MOCK_resetStores()
  })

  async function rejection(promise: Promise<unknown>): Promise<ApiError> {
    const settled = promise.then(
      () => null,
      (e: unknown) => e,
    )
    await vi.advanceTimersByTimeAsync(1000)
    const error = await settled
    expect(error).toBeInstanceOf(ApiError)
    return error as ApiError
  }

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

  test('propose -> sign off by a different account applies the value and logs both steps', async () => {
    await fast(MOCK_proposeSetting({ field: 'fn_fp_cost_ratio', proposed_value: 12 }, 'a.sharma'))
    expect((await fast(MOCK_getSettings())).fn_fp_cost_ratio).toBe(10)

    const after = await fast(MOCK_signoffSetting({ field: 'fn_fp_cost_ratio' }, 'r.mehta'))
    expect(after.fn_fp_cost_ratio).toBe(12)
    expect(after.pending_changes.some((p) => p.field === 'fn_fp_cost_ratio')).toBe(false)

    const configEvents = (await fast(MOCK_listEvents())).filter(
      (e) => e.event_type === 'config_change' && e.payload.field === 'fn_fp_cost_ratio',
    )
    expect(configEvents.map((e) => e.payload.stage)).toEqual(['proposed', 'finalized'])
    expect(new Set((await fast(MOCK_listEvents())).map((e) => e.event_id)).size).toBe(
      (await fast(MOCK_listEvents())).length,
    )
  })

  test('the proposer cannot sign off their own change (403), and nothing changes', async () => {
    const error = await rejection(MOCK_signoffSetting({ field: 'pda_threshold' }, 'r.mehta'))
    expect(error.status).toBe(403)
    const settings = await fast(MOCK_getSettings())
    expect(settings.pda_threshold).toBe(0.05)
    expect(settings.pending_changes).toHaveLength(1)
  })

  test('one pending change per value (409), sign-off with nothing pending (404), bad values (422)', async () => {
    expect(
      (
        await rejection(
          MOCK_proposeSetting({ field: 'pda_threshold', proposed_value: 0.06 }, 'a.sharma'),
        )
      ).status,
    ).toBe(409)
    expect(
      (await rejection(MOCK_signoffSetting({ field: 'fn_fp_cost_ratio' }, 'a.sharma'))).status,
    ).toBe(404)
    for (const [field, value] of [
      ['fn_fp_cost_ratio', 0],
      ['fn_fp_cost_ratio', Number.NaN],
      ['confirmed_outcome_fn_ceiling', 1.5],
    ] as const) {
      expect(
        (await rejection(MOCK_proposeSetting({ field, proposed_value: value }, 'a.sharma'))).status,
      ).toBe(422)
    }
  })

  test('returned settings are copies: mutating one never changes the store', async () => {
    const settings = await fast(MOCK_getSettings())
    settings.pending_changes.length = 0
    settings.pda_threshold = 0.9
    const again = await fast(MOCK_getSettings())
    expect(again.pda_threshold).toBe(0.05)
    expect(again.pending_changes).toHaveLength(1)
  })
})
