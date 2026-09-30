import type { ApiClient } from './client'
import { unwrap } from './errors'
import {
  MOCK_getCorrectiveStatus,
  MOCK_getWorklist,
  type MOCK_CorrectiveStatusResponse,
  type MOCK_WorklistResponse,
} from './mocks'
import type { components } from './schema'

export type SettingsResponse = components['schemas']['SettingsResponse']
export type PendingSettingChange = components['schemas']['PendingSettingChange']
export type SettingsProposalRequest = components['schemas']['SettingsProposalRequest']
export type SettingsSignoffRequest = components['schemas']['SettingsSignoffRequest']
export type SettingField = SettingsProposalRequest['field']

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

/** `GET /settings/worklist`. MOCKED: blocked on Block 4a (backend route not merged; BLOCKERS.md). */
export function getWorklist(): Promise<MOCK_WorklistResponse> {
  return MOCK_getWorklist()
}

/**
 * `GET /settings/corrective-status`. MOCKED: blocked on Block 4a (backend route not merged;
 * BLOCKERS.md).
 */
export function getCorrectiveStatus(): Promise<MOCK_CorrectiveStatusResponse> {
  return MOCK_getCorrectiveStatus()
}
