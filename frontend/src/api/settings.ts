import type { ApiClient } from './client'
import { unwrap } from './errors'
import type { components } from './schema'

export type SettingsResponse = components['schemas']['SettingsResponse']
export type PendingSettingChange = components['schemas']['PendingSettingChange']
export type SettingsProposalRequest = components['schemas']['SettingsProposalRequest']
export type SettingsSignoffRequest = components['schemas']['SettingsSignoffRequest']
export type SettingField = SettingsProposalRequest['field']
export type WorklistResponse = components['schemas']['WorklistResponse']
export type CorrectiveStatusResponse = components['schemas']['CorrectiveStatusResponse']

export const SETTINGS_QUERY_KEY = ['settings'] as const
export const WORKLIST_QUERY_KEY = ['settings', 'worklist'] as const
export const CORRECTIVE_STATUS_QUERY_KEY = ['settings', 'corrective-status'] as const

/** `GET /settings`: real (P5.5, identity/router.py). */
export async function getSettings(client: ApiClient): Promise<SettingsResponse> {
  return unwrap(await client.GET('/settings'))
}

/**
 * `POST /settings/propose`: real (P5.5). The real route reads the proposer from the JWT
 * (`get_current_account`), so this no longer takes an `accountId`.
 */
export async function proposeSetting(
  client: ApiClient,
  request: SettingsProposalRequest,
): Promise<PendingSettingChange> {
  return unwrap(await client.POST('/settings/propose', { body: request }))
}

/** `POST /settings/signoff`: real (P5.5). Same JWT-derived account as `proposeSetting`. */
export async function signoffSetting(
  client: ApiClient,
  request: SettingsSignoffRequest,
): Promise<SettingsResponse> {
  return unwrap(await client.POST('/settings/signoff', { body: request }))
}

/** `GET /settings/worklist`: real (Block 4a, capa/router.py). */
export async function getWorklist(client: ApiClient): Promise<WorklistResponse> {
  return unwrap(await client.GET('/settings/worklist'))
}

/**
 * `GET /settings/corrective-status`: real (Block 4a, capa/router.py). `fn_rate`/`fp_rate` are
 * nullable - a zero-denominator rate (e.g. zero Confirmed Defective outcomes so far) is genuinely
 * uncomputable, not `0%` (rule 7); callers must render `null` as "n/a", never coerce it.
 */
export async function getCorrectiveStatus(client: ApiClient): Promise<CorrectiveStatusResponse> {
  return unwrap(await client.GET('/settings/corrective-status'))
}
