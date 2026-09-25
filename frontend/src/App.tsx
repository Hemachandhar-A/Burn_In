import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { BrowserRouter } from 'react-router-dom'
import { ApiClientProvider } from './api/ApiClientProvider'
import { AppRoutes } from './AppRoutes'
import { AuthProvider } from './auth/AuthProvider'

export default function App() {
  const [queryClient] = useState(() => new QueryClient())
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ApiClientProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </ApiClientProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}
