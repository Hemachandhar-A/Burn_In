/**
 * A verdict shown verbatim (rule 10: the frontend never relabels what the backend sends). Color
 * is a reinforcing signal only - the badge text always carries the meaning on its own.
 */
const SEVERITY: Record<string, 'pass' | 'watch' | 'reject'> = {
  PASS: 'pass',
  ACCEPT: 'pass',
  LOT_ON_TRACK: 'pass',
  WATCH: 'watch',
  HOLD: 'watch',
  REVIEW: 'watch',
  LOT_AT_RISK: 'watch',
  REJECT: 'reject',
  STOP_RUN_RECOMMENDED: 'reject',
}

export function VerdictBadge({ verdict }: { verdict: string }) {
  const tier = SEVERITY[verdict] ?? 'watch'
  return <span className={`badge badge-${tier}`}>{verdict.replace(/_/g, ' ')}</span>
}
