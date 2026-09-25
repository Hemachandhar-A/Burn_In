import { useMemo, type ReactNode } from 'react'
import { useAuth } from '../auth/AuthContext'
import { ApiClientContext } from './ApiClientContext'
import { createApiClient, resolveApiBaseUrl, type ApiEnv } from './client'

interface ApiClientProviderProps {
  children: ReactNode
  /** Tests only; defaults to Vite's import.meta.env. */
  env?: ApiEnv
  /** Tests only; defaults to the global fetch. */
  fetch?: (input: Request) => Promise<Response>
}

/**
 * One client for the app's lifetime. It reads the token per request (getToken) and reports a
 * 401 back to AuthContext, which signs out if that token is still the current one.
 */
export function ApiClientProvider({ children, env, fetch }: ApiClientProviderProps) {
  const { getToken, handleUnauthorized } = useAuth()

  const built = useMemo(() => {
    try {
      const baseUrl = resolveApiBaseUrl(env)
      return {
        client: createApiClient({ baseUrl, getToken, onUnauthorized: handleUnauthorized, fetch }),
      }
    } catch (error) {
      return { error: error instanceof Error ? error.message : String(error) }
    }
  }, [env, fetch, getToken, handleUnauthorized])

  if ('error' in built) {
    return (
      <section className="screen" role="alert">
        <h1>Configuration error</h1>
        <p>{built.error}</p>
      </section>
    )
  }
  return <ApiClientContext.Provider value={built.client}>{children}</ApiClientContext.Provider>
}
