import type { SongEvent } from '../../api/types'

const STAGE_LABELS: Record<string, string> = {
  ingest: 'Analyzing audio',
  lyrics: 'Finding lyrics',
  align: 'Aligning lyrics to audio',
  annotate: 'Annotating text',
  render: 'Rendering subtitles',
  separate: 'Removing vocals (instrumental)',
}

const STATE_ICONS: Record<string, string> = {
  queued: '·',
  running: '⟳',
  done: '✓',
  failed: '✗',
  skipped: '↷',
}

export function JobProgress({ event }: { event: SongEvent | null }) {
  if (!event) return <div className="job-progress-empty">Waiting for progress…</div>
  return (
    <ul className="job-progress">
      {event.jobs.map((job, i) => (
        <li key={`${job.stage}-${i}`} className={`job job--${job.state}`}>
          <span className="job-icon">{STATE_ICONS[job.state] ?? '·'}</span>
          <span className="job-label">{STAGE_LABELS[job.stage] ?? job.stage}</span>
          {job.error ? <span className="job-error">{job.error}</span> : null}
        </li>
      ))}
    </ul>
  )
}
