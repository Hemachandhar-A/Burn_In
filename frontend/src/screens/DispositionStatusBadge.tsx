import type { components } from '../api/schema'

export type DispositionStatus = NonNullable<components['schemas']['PartDetailResponse']['disposition_status']>

/** The sign-off state the backend derived from the stored sign-offs (identity/status.py, the Lead's rule in
 * docs/FIXES_PLAN.md) - shown as sent, never worked out here. Colour only reinforces: the text always says it. */
export const STATUS_LABELS: Record<DispositionStatus, string> = {
  NONE: 'No sign-off yet',
  ACCEPT_RECORDED: 'Accepted',
  HOLD_RECORDED: 'Held for retest',
  REJECT_PENDING_SECOND: 'REJECT: awaiting second sign-off',
  REJECT_FINAL: 'REJECT: final',
  CONFLICT: 'Conflict: sign-offs disagree',
}

const TONE: Record<DispositionStatus, string> = {
  NONE: 'muted',
  ACCEPT_RECORDED: 'pass',
  HOLD_RECORDED: 'watch',
  REJECT_PENDING_SECOND: 'watch',
  REJECT_FINAL: 'reject',
  CONFLICT: 'watch',
}

export function DispositionStatusBadge({ status }: { status: DispositionStatus | null | undefined }) {
  // An older stored/cached response carries no status: nothing is claimed.
  if (!status) return null
  return (
    <span className={`badge badge-${TONE[status]}`} data-testid="disposition-status" data-status={status}>
      {STATUS_LABELS[status]}
    </span>
  )
}
