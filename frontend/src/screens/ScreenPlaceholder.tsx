import type { ReactNode } from 'react'
import { screenById, type ScreenId } from './registry'

/** Stand-in for a screen whose Part 10 session hasn't built it yet (P1.9 scaffold). */
export function ScreenPlaceholder({ id, children }: { id: ScreenId; children?: ReactNode }) {
  const { title, e6Step, session } = screenById(id)
  return (
    <section className="screen">
      <h1>{title}</h1>
      {children}
      <p className="placeholder-note">
        Placeholder. This screen (essential-features.md E6 step {e6Step}) is built in session{' '}
        {session}.
      </p>
    </section>
  )
}
