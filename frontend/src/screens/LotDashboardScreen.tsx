import { useParams } from 'react-router-dom'
import { ScreenPlaceholder } from './ScreenPlaceholder'

export function LotDashboardScreen() {
  const { lotId } = useParams()
  return (
    <ScreenPlaceholder id="lotDashboard">
      <p>
        Lot: <code data-testid="route-id">{lotId}</code>
      </p>
    </ScreenPlaceholder>
  )
}
