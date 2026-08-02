import type { SongStatus } from '../../api/types'

const LABELS: Record<SongStatus, string> = {
  pending: 'Pending',
  processing: 'Processing',
  ready: 'Ready',
  needs_review: 'Needs review',
  failed: 'Failed',
}

export function StatusBadge({ status }: { status: SongStatus }) {
  return <span className={`badge badge--${status}`}>{LABELS[status] ?? status}</span>
}
