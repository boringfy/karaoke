import { coverUrl } from '../../api/media'
import { deleteSong } from '../../api/songs'
import type { Song } from '../../api/types'
import { useSongEvents } from '../../hooks/useSongEvents'
import { playSong } from '../../player/usePlaybackEngine'
import { useLibraryStore } from '../../stores/libraryStore'
import { useQueueStore } from '../../stores/queueStore'
import { useUiStore } from '../../stores/uiStore'
import { StatusBadge } from './StatusBadge'

function fmtDuration(sec: number | null): string {
  if (sec == null) return '—'
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

interface Props {
  song: Song
  onEdit: (song: Song) => void
}

export function SongRow({ song, onEdit }: Props) {
  const toast = useUiStore((s) => s.toast)
  const openWizard = useUiStore((s) => s.openWizard)
  const addToQueue = useQueueStore((s) => s.add)
  const processing = song.status === 'processing' || song.status === 'pending'
  const liveEvent = useSongEvents(song.id, processing)
  const playable = song.status === 'ready' || song.status === 'needs_review'

  const runningStage = liveEvent?.jobs.find((j) => j.state === 'running')?.stage

  const onDelete = () => {
    if (!window.confirm(`Delete "${song.title}" and all its files? This cannot be undone.`)) return
    void deleteSong(song.id)
      .then(() => useLibraryStore.getState().refresh())
      .catch((err) => toast(err instanceof Error ? err.message : String(err), 'error'))
  }

  return (
    <tr className="song-row">
      <td className="song-cell-title">
        <div className="song-title-wrap">
          {song.has_cover ? (
            <img
              className="song-cover"
              src={coverUrl(song.id, song.updated_at)}
              alt=""
              loading="lazy"
            />
          ) : (
            <div className="song-cover song-cover--placeholder">♪</div>
          )}
          <div>
            <div className="song-title">{song.title}</div>
            {song.artist ? <div className="song-artist">{song.artist}</div> : null}
          </div>
        </div>
      </td>
      <td>{fmtDuration(song.duration_sec)}</td>
      <td>
        <StatusBadge status={song.status} />
        {runningStage ? <span className="stage-hint"> {runningStage}…</span> : null}
      </td>
      <td className="song-cell-assets">
        {song.has_original ? <span className="asset" title="Original vocals">Voc</span> : null}
        {song.has_instrumental ? (
          <span className="asset" title={`Instrumental (${song.instrumental_source ?? ''})`}>
            Inst
          </span>
        ) : null}
        {song.has_video ? <span className="asset" title="Music video">MV</span> : null}
        {song.has_subtitle ? <span className="asset" title="Karaoke subtitles">Lyr</span> : null}
      </td>
      <td className="song-cell-actions">
        <button className="primary" disabled={!playable} onClick={() => void playSong(song)}>
          ▶ Play
        </button>
        <button
          disabled={!playable}
          onClick={() => {
            addToQueue({ songId: song.id, title: song.title, artist: song.artist })
            toast(`Added "${song.title}" to queue`)
          }}
        >
          + Queue
        </button>
        <button onClick={() => openWizard(song.id)}>Files</button>
        <button onClick={() => onEdit(song)}>Edit</button>
        <button className="danger" onClick={onDelete}>
          Delete
        </button>
      </td>
    </tr>
  )
}
