import {
  MOCK_getCorrectiveStatus,
  MOCK_getSettings,
  MOCK_getWorklist,
  MOCK_proposeSetting,
  MOCK_signoffSetting,
  type MOCK_CorrectiveStatusResponse,
  type MOCK_PendingSettingChange,
  type MOCK_SettingsProposalRequest,
  type MOCK_SettingsResponse,
  type MOCK_SettingsSignoffRequest,
  type MOCK_WorklistResponse,
} from './mocks'

export const SETTINGS_QUERY_KEY = ['settings'] as const
export const WORKLIST_QUERY_KEY = ['settings', 'worklist'] as const
export const CORRECTIVE_STATUS_QUERY_KEY = ['settings', 'corrective-status'] as const

/**
 * `GET /settings`. MOCKED: not in the live schema (P5.5, identity/router.py; BLOCKERS.md). When it
 * lands, each function here takes the ApiClient and calls its route through it; the two POSTs stop
 * taking `accountId`, since the real routes read the account from the JWT.
 */
export function getSettings(): Promise<MOCK_SettingsResponse> {
  return MOCK_getSettings()
}

/** `POST /settings/propose`. MOCKED (P5.5). */
export function proposeSetting(
  request: MOCK_SettingsProposalRequest,
  accountId: string,
): Promise<MOCK_PendingSettingChange> {
  return MOCK_proposeSetting(request, accountId)
}

/** `POST /settings/signoff`. MOCKED (P5.5). */
export function signoffSetting(
  request: MOCK_SettingsSignoffRequest,
  accountId: string,
): Promise<MOCK_SettingsResponse> {
  return MOCK_signoffSetting(request, accountId)
}

/** `GET /settings/worklist`. MOCKED (P5.8, capa/router.py). */
export function getWorklist(): Promise<MOCK_WorklistResponse> {
  return MOCK_getWorklist()
}

/** `GET /settings/corrective-status`. MOCKED (P5.8, capa/router.py). */
export function getCorrectiveStatus(): Promise<MOCK_CorrectiveStatusResponse> {
  return MOCK_getCorrectiveStatus()
}
