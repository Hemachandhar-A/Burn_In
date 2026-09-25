import { useParams } from 'react-router-dom'
import { ScreenPlaceholder } from './ScreenPlaceholder'

export function PartDetailScreen() {
  const { componentId } = useParams()
  return (
    <ScreenPlaceholder id="partDetail">
      <p>
        Component: <code>{componentId}</code>
      </p>
    </ScreenPlaceholder>
  )
}
