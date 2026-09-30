import { createContext, useContext } from 'react'

/**
 * The lot and part this session was last working on. It gives the Lot Dashboard and Part
 * Detail nav items somewhere to go, since both screens need an id. Plain in-memory state held
 * by AppShell. It's gone on sign-out or refresh, like the session it belongs to.
 */
export interface WorkingLot {
  lastLotId: string | null
  lastPartId: string | null
  /** A screen that just produced or opened a lot (e.g. Ingest after an upload) records it here. */
  rememberLot: (lotId: string) => void
}

const NONE: WorkingLot = { lastLotId: null, lastPartId: null, rememberLot: () => {} }

export const WorkingLotContext = createContext<WorkingLot>(NONE)

export function useWorkingLot(): WorkingLot {
  return useContext(WorkingLotContext)
}
