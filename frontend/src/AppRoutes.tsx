import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth/AuthContext'
import { HistoryScreen } from './screens/HistoryScreen'
import { IngestScreen } from './screens/IngestScreen'
import { LoginScreen } from './screens/LoginScreen'
import { LotDashboardScreen } from './screens/LotDashboardScreen'
import { NotFoundScreen } from './screens/NotFoundScreen'
import { PartDetailScreen } from './screens/PartDetailScreen'
import { ProjectBrowserScreen } from './screens/ProjectBrowserScreen'
import { screenById } from './screens/registry'
import { SettingsScreen } from './screens/SettingsScreen'
import { AppShell } from './shell/AppShell'
import { RequireAuth } from './shell/RequireAuth'

export function AppRoutes() {
  const { session } = useAuth()
  const home = screenById('ingest').path

  return (
    <Routes>
      <Route
        path={screenById('login').path}
        element={session ? <Navigate to={home} replace /> : <LoginScreen />}
      />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to={home} replace />} />
          <Route path={home} element={<IngestScreen />} />
          <Route path={screenById('lotDashboard').path} element={<LotDashboardScreen />} />
          <Route path={screenById('partDetail').path} element={<PartDetailScreen />} />
          <Route path={screenById('projects').path} element={<ProjectBrowserScreen />} />
          <Route path={screenById('history').path} element={<HistoryScreen />} />
          <Route path={screenById('settings').path} element={<SettingsScreen />} />
          <Route path="*" element={<NotFoundScreen />} />
        </Route>
      </Route>
    </Routes>
  )
}
