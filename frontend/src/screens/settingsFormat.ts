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

/** Up to 2 decimals, trailing zeros dropped, never exponent notation. */
function trim(value: number): string {
  return String(Math.round(value * 100) / 100)
}

/** A percentage with one decimal, or more if the value needs it (5.5%, 5.25%). */
export function formatPercent(fraction: number): string {
  const pct = fraction * 100
  const rounded = Math.round(pct * 100) / 100
  return `${Number.isInteger(rounded * 10) ? rounded.toFixed(1) : trim(rounded)}%`
}

export function formatSettingValue(field: MOCK_SettingField, value: number): string {
  return isRatio(field) ? `${trim(value)}:1` : formatPercent(value)
}

/** The number a person types for a field: the ratio's N, or the percentage (5.5 for 0.055). */
export function toInputValue(field: MOCK_SettingField, value: number): string {
  return isRatio(field) ? trim(value) : trim(value * 100)
}

/** The wire value for what a person typed, or null if it isn't a usable number. */
export function fromInputValue(field: MOCK_SettingField, input: string): number | null {
  const trimmed = input.trim()
  if (!/^\d*\.?\d+$/.test(trimmed)) return null
  const n = Number(trimmed)
  if (!Number.isFinite(n) || n <= 0) return null
  if (isRatio(field)) return n
  if (n > 100) return null
  // Rounded so 5.5 -> 0.055 exactly, not 0.05499999999999999.
  return Math.round(n * 1e4) / 1e6
}

/** `2026-09-15T11:20:40.123Z` -> `2026-09-15 11:20:40`. A timestamp with no offset is UTC. */
export function formatUtc(iso: string): string {
  const ms = parseUtc(iso)
  return Number.isNaN(ms) ? iso : new Date(ms).toISOString().slice(0, 19).replace('T', ' ')
}

/** Epoch ms. Storage writes datetime.now(UTC), and SQLite drops the offset on the way back. */
export function parseUtc(iso: string): number {
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(iso)
  return Date.parse(hasZone ? iso : `${iso}Z`)
}
