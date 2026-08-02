import { nudgeLyricOffset } from '../../player/lyricSync'
import { engine } from '../../player/PlaybackEngine'
import { playNextInQueue } from '../../player/usePlaybackEngine'
import { usePlayerStore } from '../../stores/playerStore'
import { useQueueStore } from '../../stores/queueStore'
import { SeekBar } from './SeekBar'

export function TransportBar() {
  const song = usePlayerStore((s) => s.song)
  const status = usePlayerStore((s) => s.status)
  const track = usePlayerStore((s) => s.track)
  const offsetMs = usePlayerStore((s) => s.subtitle?.offset_ms ?? null)
  const queueLen = useQueueStore((s) => s.queue.length)
  const queueIdx = useQueueStore((s) => s.currentIndex)

  if (!song) return null
  const canToggle = song.has_original && song.has_instrumental
  const hasNext = queueIdx + 1 < queueLen

  return (
    <div className="transport">
      <SeekBar />
      <div className="transport-row">
        <div className="transport-meta">
          <div className="transport-title">{song.title}</div>
          {song.artist ? <div className="transport-artist">{song.artist}</div> : null}
        </div>
        <div className="transport-buttons">
          <button title="Restart (r)" onClick={() => engine.restart()}>
            ⟲
          </button>
          <button title="Back 10s (←)" onClick={() => engine.seekBy(-10)}>
            −10s
          </button>
          <button
            className="transport-play"
            title="Play/Pause (space)"
            onClick={() => void engine.togglePlay()}
          >
            {status === 'playing' ? '⏸' : '▶'}
          </button>
          <button title="Forward 10s (→)" onClick={() => engine.seekBy(10)}>
            +10s
          </button>
          <button
            title={hasNext ? 'Next in queue (n)' : 'Queue is empty'}
            disabled={!hasNext}
            onClick={() => void playNextInQueue()}
          >
            ⏭
          </button>
        </div>
        <div className="transport-right">
          {offsetMs !== null ? (
            <div className="lyric-sync" title="Lyric sync — shift subtitles earlier/later ( [ and ] )">
              <button onClick={() => nudgeLyricOffset(-100)}>−</button>
              <span className="lyric-sync-value">
                {offsetMs === 0 ? 'sync' : `${offsetMs > 0 ? '+' : ''}${(offsetMs / 1000).toFixed(1)}s`}
              </span>
              <button onClick={() => nudgeLyricOffset(100)}>+</button>
            </div>
          ) : null}
          {canToggle ? (
            <div className="track-toggle" title="Toggle vocals (o)">
              <button
                className={track === 'instrumental' ? 'active' : ''}
                onClick={() => engine.setTrack('instrumental')}
              >
                Karaoke
              </button>
              <button
                className={track === 'original' ? 'active' : ''}
                onClick={() => engine.setTrack('original')}
              >
                Original
              </button>
            </div>
          ) : song.has_original && !song.has_instrumental ? (
            <span className="track-toggle-hint" title="The instrumental is generated automatically">
              Preparing karaoke…
            </span>
          ) : null}
          <button
            title="Fullscreen (f)"
            onClick={() => void window.karaoke?.toggleFullscreen()}
          >
            ⛶
          </button>
        </div>
      </div>
    </div>
  )
}
