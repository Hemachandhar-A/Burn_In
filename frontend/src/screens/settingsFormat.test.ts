import { describe, expect, test } from 'vitest'
import {
  formatNumber,
  formatPercent,
  formatSettingValue,
  formatUtc,
  fromInputValue,
  parseUtc,
  sortableTime,
  toInputValue,
} from './settingsFormat'

describe('fromInputValue (P1.12 edge-case review)', () => {
  test.each([
    ['12', 12],
    ['12:1', 12],
    [' 12 : 1 ', 12],
    ['.5', 0.5],
    ['7.', 7],
    ['2.25', 2.25],
  ])('ratio %j -> %j', (input, expected) => {
    expect(fromInputValue('fn_fp_cost_ratio', input)).toBe(expected)
  })

  test.each([
    ['5.5', 0.055],
    ['5.5%', 0.055],
    ['5.5 %', 0.055],
    ['5.', 0.05],
    ['100', 1],
    ['0.01', 0.0001],
  ])('percent %j -> %j', (input, expected) => {
    expect(fromInputValue('pda_threshold', input)).toBe(expected)
  })

  test.each([
    '',
    ' ',
    'abc',
    '0',
    '0.0',
    '-3',
    '+5',
    '1e3',
    '5,5',
    '5..5',
    '12:2',
    'NaN',
    'Infinity',
  ])('ratio rejects %j', (input) => {
    expect(fromInputValue('fn_fp_cost_ratio', input)).toBeNull()
  })

  test.each(['100.01', '150', '0.00001', '5%%', '5.5:1'])('percent rejects %j', (input) => {
    expect(fromInputValue('confirmed_outcome_fn_ceiling', input)).toBeNull()
  })

  test('the prefilled value round-trips exactly, so submitting it unchanged proposes no change', () => {
    for (const value of [0.05, 0.055, 0.05125, 0.0333, 0.1, 1]) {
      expect(fromInputValue('pda_threshold', toInputValue('pda_threshold', value))).toBe(value)
    }
    for (const value of [10, 12.5, 3.125, 0.75]) {
      expect(fromInputValue('fn_fp_cost_ratio', toInputValue('fn_fp_cost_ratio', value))).toBe(
        value,
      )
    }
  })
})

describe('display formatting', () => {
  test('percentages keep the precision they need', () => {
    expect(formatPercent(0.05)).toBe('5.0%')
    expect(formatPercent(0.055)).toBe('5.5%')
    expect(formatPercent(0.0525)).toBe('5.25%')
    expect(formatPercent(0.028)).toBe('2.8%')
    expect(formatPercent(Number.NaN)).toBe('—')
  })

  test('the ratio is N:1', () => {
    expect(formatSettingValue('fn_fp_cost_ratio', 10)).toBe('10:1')
    expect(formatSettingValue('fn_fp_cost_ratio', 12.5)).toBe('12.5:1')
    expect(formatSettingValue('fn_fp_cost_ratio', Number.POSITIVE_INFINITY)).toBe('—')
  })

  test('payload numbers lose float noise, non-numbers are null', () => {
    expect(formatNumber(60.80000000000001)).toBe('60.8')
    expect(formatNumber(0)).toBe('0')
    expect(formatNumber(null)).toBeNull()
    expect(formatNumber('60.8')).toBeNull()
    expect(formatNumber(Number.NaN)).toBeNull()
  })
})

describe('timestamps', () => {
  test('a naive timestamp is UTC; an offset one is converted to UTC', () => {
    expect(formatUtc('2026-09-15T11:20:40')).toBe('2026-09-15 11:20:40')
    expect(formatUtc('2026-09-15T11:20:40.123456')).toBe('2026-09-15 11:20:40')
    expect(formatUtc('2026-09-15T11:20:40Z')).toBe('2026-09-15 11:20:40')
    expect(formatUtc('2026-09-15T01:00:00+05:30')).toBe('2026-09-14 19:30:00')
    expect(parseUtc('2026-09-15T01:00:00+0530')).toBe(Date.parse('2026-09-14T19:30:00Z'))
  })

  test('an unparseable timestamp is shown raw and sorts as the oldest', () => {
    expect(formatUtc('not a date')).toBe('not a date')
    expect(sortableTime('not a date')).toBe(-Infinity)
    expect(sortableTime('2026-09-15T11:20:40')).toBe(Date.parse('2026-09-15T11:20:40Z'))
  })
})
