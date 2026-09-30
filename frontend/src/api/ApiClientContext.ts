import { createContext, useContext } from 'react'
import type { ApiClient } from './client'

export const ApiClientContext = createContext<ApiClient | null>(null)

/** The generated, typed client carrying the current session's JWT - never a raw fetch (rule 14). */
export function useApiClient(): ApiClient {
  const client = useContext(ApiClientContext)
  if (!client) throw new Error('useApiClient must be used inside an <ApiClientProvider>')
  return client
}
