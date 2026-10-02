import { HashRouter } from 'react-router-dom'
import { AppProviders } from './AppProviders'
import { AppRoutes } from './AppRoutes'

/**
 * HashRouter, not BrowserRouter: screen paths (/lots/:id, /parts/:id, /projects, /settings)
 * share names with API routes (IMPLEMENTATION_PLAN.md Part 5.6). In the single-process demo
 * build FastAPI serves both from one origin, so a refresh on a real /lots/X path would hit the
 * API and show JSON. With the hash, the server only ever serves "/" and needs no SPA fallback.
 */
export default function App() {
  return (
    <AppProviders>
      <HashRouter>
        <AppRoutes />
      </HashRouter>
    </AppProviders>
  )
}
