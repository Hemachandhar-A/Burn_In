/**
 * The seven screens of essential-features.md E6, in E6 order - the one list the router, the
 * nav shell and the tests all read, so a screen can't exist in one place and be missing from
 * another. `session` is the Part 10 session that builds it out from a placeholder.
 */
export const SCREENS = [
  { id: 'login', title: 'Login', path: '/login', e6Step: 1, session: 'P1.10', inNav: false },
  { id: 'ingest', title: 'Ingest', path: '/ingest', e6Step: 2, session: 'P1.10', inNav: true },
  {
    id: 'lotDashboard',
    title: 'Lot Dashboard',
    path: '/lots/:lotId',
    e6Step: 3,
    session: 'P1.11',
    inNav: false,
  },
  {
    id: 'partDetail',
    title: 'Part Detail',
    path: '/parts/:componentId',
    e6Step: 4,
    session: 'P1.11',
    inNav: false,
  },
  {
    id: 'projects',
    title: 'Project Browser',
    path: '/projects',
    e6Step: 5,
    session: 'P1.12',
    inNav: true,
  },
  { id: 'history', title: 'History', path: '/history', e6Step: 6, session: 'P1.12', inNav: true },
  {
    id: 'settings',
    title: 'Settings',
    path: '/settings',
    e6Step: 7,
    session: 'P1.12',
    inNav: true,
  },
] as const

export type ScreenId = (typeof SCREENS)[number]['id']

export function screenById(id: ScreenId) {
  return SCREENS.find((s) => s.id === id)!
}

function segment(id: string, what: string): string {
  if (id.trim() === '') throw new Error(`Cannot link to a screen with a blank ${what}`)
  // encodeURIComponent leaves "." alone, and "." / ".." segments would read as relative paths.
  return /^\.+$/.test(id) ? id.replace(/\./g, '%2E') : encodeURIComponent(id)
}

/** Link to a lot's dashboard. Always build these links here, never by string concatenation. */
export function pathToLot(lotId: string): string {
  return `/lots/${segment(lotId, 'lot id')}`
}

/** Link to a part's detail screen. Same rule as pathToLot. */
export function pathToPart(componentId: string): string {
  return `/parts/${segment(componentId, 'component id')}`
}
