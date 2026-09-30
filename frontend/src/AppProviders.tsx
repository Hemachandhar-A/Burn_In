import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useCallback, useState, type ReactNode } from 'react'
import { ApiClientProvider } from './api/ApiClientProvider'
import type { Session } from './auth/AuthContext'
import { AuthProvider } from './auth/AuthProvider'

interface AppProvidersProps {
  children: ReactNode
  /** Tests only: supply the cache to inspect it. */
  queryClient?: QueryClient
  /** Tests only: start signed in (still in memory only). */
  initialSession?: Session | null
}

/**
 * Server state, auth and the API client. Whenever a session ends - Sign out, a 401, or a
 * different account signing in - the query cache is dropped, so one account never sees data
 * fetched under another's token.
 */
export function AppProviders({ children, queryClient, initialSession }: AppProvidersProps) {
  const [client] = useState(() => queryClient ?? new QueryClient())
  const clearCache = useCallback(() => client.clear(), [client])

  return (
    <QueryClientProvider client={client}>
      <AuthProvider initialSession={initialSession} onSessionEnd={clearCache}>
        <ApiClientProvider>{children}</ApiClientProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}
