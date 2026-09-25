import { useMemo, type ReactNode } from 'react'
import { useAuth } from '../auth/AuthContext'
import { ApiClientContext } from './ApiClientContext'
import { createApiClient, resolveApiBaseUrl } from './client'

export function ApiClientProvider({ children }: { children: ReactNode }) {
  const token = useAuth().session?.token ?? null
  const client = useMemo(
    () => createApiClient({ baseUrl: resolveApiBaseUrl(), getToken: () => token }),
    [token],
  )
  return <ApiClientContext.Provider value={client}>{children}</ApiClientContext.Provider>
}
