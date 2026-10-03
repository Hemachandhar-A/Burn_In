import { describe, expect, it } from 'vitest'
import { formatQuantity, scaleFor, scaleForSeries } from './units'

const CANONICAL: Record<string, string> = { iddq: 'uA', leakage: 'nA', prop_delay: 'ns' }
const TEN_VALUES = [0.0042, 0.37, 1, 4.5, 12, 999, 1000, 10000, 52380, 3.2e6]

describe('scaleFor (T13 round trip)', () => {
  for (const [parameter, unit] of Object.entries(CANONICAL)) {
    it(`displayed value times its factor is the canonical value: ${parameter}`, () => {
      for (const v of TEN_VALUES) {
        const scale = scaleFor(v, unit)
        const shown = v / scale.factor
        expect(shown * scale.factor).toBeCloseTo(v, 9)
        const edge = ['pA', 'ps', 'A', 's'].includes(scale.unit)
        expect(edge || (Math.abs(shown) >= 1 - 1e-9 && Math.abs(shown) < 1000 + 1e-6)).toBe(true)
      }
    })
  }

  it('shows 10000 nA as 10 uA', () => {
    expect(scaleFor(10000, 'nA').unit).toBe('uA')
    expect(formatQuantity(10000, 'nA')).toBe('10 uA')
    expect(formatQuantity(45000, 'nA')).toBe('45 uA')
    expect(formatQuantity(7.07, 'ns')).toBe('7.07 ns')
    expect(formatQuantity(0.0042, 'uA')).toBe('4.2 nA')
    expect(formatQuantity(2500, 'ns')).toBe('2.5 us')
  })

  it('leaves zero, missing and unknown units alone', () => {
    expect(scaleFor(0, 'nA')).toEqual({ unit: 'nA', factor: 1 })
    expect(scaleFor(5, null)).toEqual({ unit: '', factor: 1 })
    expect(scaleFor(5, 'furlongs')).toEqual({ unit: 'furlongs', factor: 1 })
    expect(formatQuantity(5, null)).toBe('5')
    expect(formatQuantity(Number.NaN, 'nA')).toBe('—')
    expect(formatQuantity(null, 'nA')).toBe('—')
  })

  it('keeps the sign of a negative value', () => {
    const scale = scaleFor(-2500, 'nA')
    expect(scale.unit).toBe('uA')
    expect(formatQuantity(-2500, 'nA')).toBe('-2.5 uA')
  })

  it('uses one scale for a whole series, from its largest magnitude', () => {
    const scale = scaleForSeries([9000, 10500, null, 9800], 'nA')
    expect(scale.unit).toBe('uA')
    expect(scaleForSeries([], 'nA')).toEqual({ unit: 'nA', factor: 1 })
  })
})
