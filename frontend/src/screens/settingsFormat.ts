import type { MOCK_SettingField } from '../api/mocks'

/** The three live-editable values (E6 screen 7, E10 step 5, E13 step 6), in display order. */
export const SETTING_FIELDS: readonly MOCK_SettingField[] = [
  'fn_fp_cost_ratio',
  'pda_threshold',
  'confirmed_outcome_fn_ceiling',
]

export const SETTING_LABELS: Record<MOCK_SettingField, string> = {
  fn_fp_cost_ratio: 'FN:FP cost ratio',
  pda_threshold: 'PDA threshold',
  confirmed_outcome_fn_ceiling: 'Confirmed-outcome FN ceiling',
}

export function isSettingField(value: unknown): value is MOCK_SettingField {
  return typeof value === 'string' && (SETTING_FIELDS as readonly string[]).includes(value)
}

/** The cost ratio is shown as `N:1`; the two rates are fractions on the wire, shown as percent. */
export function isRatio(field: MOCK_SettingField): boolean {
  return field === 'fn_fp_cost_ratio'
}

/** Rounded to `decimals`, trailing zeros dropped, never exponent notation for sane values. */
function trim(value: number, decimals = 2): string {
  const factor = 10 ** decimals
  return String(Math.round(value * factor) / factor)
}

/** A percentage with one decimal, or more if the value needs it (5.5%, 5.25%). */
export function formatPercent(fraction: number): string {
  if (!Number.isFinite(fraction)) return '—'
  const rounded = Math.round(fraction * 100 * 100) / 100
  return `${Number.isInteger(rounded * 10) ? rounded.toFixed(1) : trim(rounded)}%`
}

export function formatSettingValue(field: MOCK_SettingField, value: number): string {
  if (!Number.isFinite(value)) return '—'
  return isRatio(field) ? `${trim(value)}:1` : formatPercent(value)
}

/**
 * The number a person types for a field: the ratio's N, or the percentage (5.5 for 0.055). Kept
 * to 4 decimals, not the 2 shown elsewhere: the form is prefilled with this, and a lossy prefill
 * would silently propose a different value if submitted unchanged.
 */
export function toInputValue(field: MOCK_SettingField, value: number): string {
  return isRatio(field) ? trim(value, 4) : trim(value * 100, 4)
}

/**
 * The wire value for what a person typed, or null if it isn't a usable number. Accepts the unit
 * the value is shown with (`12:1`, `5.5%`) and a bare trailing dot (`5.`); rejects signs,
 * exponents and comma decimals rather than guess at them.
 */
export function fromInputValue(field: MOCK_SettingField, input: string): number | null {
  let text = input.trim()
  if (isRatio(field)) text = text.replace(/\s*:\s*1$/, '')
  else text = text.replace(/\s*%$/, '')
  if (!/^(\d+\.?\d*|\.\d+)$/.test(text)) return null
  const n = Number(text)
  if (!Number.isFinite(n) || n <= 0) return null
  if (isRatio(field)) return n
  if (n > 100) return null
  // Rounded so 5.5 -> 0.055 exactly, not 0.05499999999999999. A percentage so small that it
  // rounds to 0 is rejected here rather than sent as 0.
  const fraction = Math.round(n * 1e4) / 1e6
  return fraction > 0 ? fraction : null
}

/** A number from a stored payload, rounded to 4 decimals to hide float noise; null otherwise. */
export function formatNumber(value: unknown): string | null {
  return typeof value === 'number' && Number.isFinite(value) ? trim(value, 4) : null
}

/** `2026-09-15T11:20:40.123Z` -> `2026-09-15 11:20:40`. A timestamp with no offset is UTC. */
export function formatUtc(iso: string): string {
  const ms = parseUtc(iso)
  return Number.isNaN(ms) ? iso : new Date(ms).toISOString().slice(0, 19).replace('T', ' ')
}

/** Epoch ms, or NaN. Storage writes datetime.now(UTC), and SQLite drops the offset on the way back. */
export function parseUtc(iso: string): number {
  if (typeof iso !== 'string') return NaN
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/i.test(iso)
  return Date.parse(hasZone ? iso : `${iso}Z`)
}

/** For sorting: an unparseable timestamp sorts as the oldest, never as NaN (which breaks sort). */
export function sortableTime(iso: string): number {
  const ms = parseUtc(iso)
  return Number.isNaN(ms) ? -Infinity : ms
}
