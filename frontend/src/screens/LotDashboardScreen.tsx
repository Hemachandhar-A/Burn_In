import { useParams } from 'react-router-dom'
import { ScreenPlaceholder } from './ScreenPlaceholder'

export function LotDashboardScreen() {
  const { lotId } = useParams()
  return (
    <ScreenPlaceholder id="lotDashboard">
      <p>
        Lot: <code>{lotId}</code>
      </p>
    </ScreenPlaceholder>
  )
}
