/**
 * The frontend twin of explain/units.py: an automatic SI prefix for a canonical-unit value
 * (10000 nA is shown as 10 uA). Same rule, same labels (ASCII "uA"), same tests, because the two
 * sides never share code. Only current and time units change prefix; any other unit is shown as
 * given. `shown * factor === value`, so the canonical number is always recoverable.
 */

// (label, power of ten relative to the family's base unit), largest first. Integer exponents, not 1e-9-style
// floats: 1e-6 / 1e-9 is 999.9999999999999, and a displayed 45 must not be 45.00000000000001.
const CURRENT: ReadonlyArray<readonly [string, number]> = [
  ['A', 0],
  ['mA', -3],
  ['uA', -6],
  ['nA', -9],
  ['pA', -12],
]
const TIME: ReadonlyArray<readonly [string, number]> = [
  ['s', 0],
  ['ms', -3],
  ['us', -6],
  ['ns', -9],
  ['ps', -12],
]
const FAMILIES = [CURRENT, TIME]

export type DisplayScale = {
  /** The label to print after the number ('' when there is no unit). */
  unit: string
  /** displayed * factor === canonical value. */
  factor: number
}

const UNCHANGED = (unit: string | null | undefined): DisplayScale => ({
  unit: (unit ?? '').trim(),
  factor: 1,
})

function familyOf(unit: string): { labels: typeof CURRENT; exponent: number } | null {
  const key = unit.trim().toLowerCase()
  for (const labels of FAMILIES) {
    const hit = labels.find(([label]) => label.toLowerCase() === key)
    if (hit) return { labels, exponent: hit[1] }
  }
  return null
}

/** The prefix that leaves |value| >= 1 with the largest unit of the family; the smallest unit when
 * the value is tinier than all of them. Zero, non-finite, missing or unknown units: unchanged. */
export function scaleFor(value: number, unit: string | null | undefined): DisplayScale {
  if (unit === null || unit === undefined || unit.trim() === '' || !Number.isFinite(value) || value === 0) {
    return UNCHANGED(unit)
  }
  const family = familyOf(unit)
  if (!family) return UNCHANGED(unit)
  const magnitude = Math.abs(value) * 10 ** family.exponent
  const [label, exponent] =
    family.labels.find(([, e]) => magnitude >= 10 ** e * (1 - 1e-12)) ?? family.labels[family.labels.length - 1]
  return { unit: label, factor: 10 ** (exponent - family.exponent) }
}

/** One scale for a whole series (a chart axis): chosen from its largest magnitude. */
export function scaleForSeries(values: ReadonlyArray<number | null | undefined>, unit: string | null | undefined): DisplayScale {
  const finite = values.filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
  if (finite.length === 0) return UNCHANGED(unit)
  return scaleFor(finite.reduce((a, b) => (Math.abs(b) > Math.abs(a) ? b : a)), unit)
}

function significant(value: number, digits: number): string {
  return String(Number(value.toPrecision(digits)))
}

/** "10 uA" for (10000, 'nA'); the bare number when there is no unit; a dash for a non-finite value. */
export function formatQuantity(value: number | null | undefined, unit: string | null | undefined, digits = 4): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  const scale = scaleFor(value, unit)
  const text = significant(value / scale.factor, digits)
  return scale.unit ? `${text} ${scale.unit}` : text
}
