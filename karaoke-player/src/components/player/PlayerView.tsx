import { useEffect } from 'react'
import { nudgeLyricOffset } from '../../player/lyricSync'
import { engine } from '../../player/PlaybackEngine'
import { playNextInQueue } from '../../player/usePlaybackEngine'
import { usePlayerStore } from '../../stores/playerStore'
import { useUiStore } from '../../stores/uiStore'
import { SubtitleOverlay } from '../../subtitles/SubtitleOverlay'
import { QueuePanel } from './QueuePanel'
import { TransportBar } from './TransportBar'
import { VideoSurface } from './VideoSurface'

export function PlayerView() {
  const song = usePlayerStore((s) => s.song)
  const status = usePlayerStore((s) => s.status)
  const error = usePlayerStore((s) => s.error)
  const setView = useUiStore((s) => s.setView)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (useUiStore.getState().view !== 'player') return
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      switch (e.key) {
        case ' ':
          e.preventDefault()
          void engine.togglePlay()
          break
        case 'ArrowLeft':
          engine.seekBy(e.shiftKey ? -30 : -10)
          break
        case 'ArrowRight':
          engine.seekBy(e.shiftKey ? 30 : 10)
          break
        case 'r':
          engine.restart()
          break
        case 'n':
          void playNextInQueue()
          break
        case 'o':
          engine.toggleTrack()
          break
        case 'f':
          void window.karaoke?.toggleFullscreen()
          break
        case '[':
          nudgeLyricOffset(-100)
          break
        case ']':
          nudgeLyricOffset(100)
          break
        case 'Escape':
          setView('library')
          break
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setView])

  return (
    <div className="player-view">
      <VideoSurface />
      <SubtitleOverlay />
      {status === 'loading' ? <div className="player-status">Loading…</div> : null}
      {status === 'error' && error ? <div className="player-status player-status--error">{error}</div> : null}
      {status === 'ended' && !song ? <div className="player-status">Queue finished</div> : null}
      {status === 'ended' && song ? <div className="player-status">Queue finished 🎤</div> : null}
      <button className="player-back" onClick={() => setView('library')}>
        ‹ Library
      </button>
      <QueuePanel />
      <TransportBar />
    </div>
  )
}
