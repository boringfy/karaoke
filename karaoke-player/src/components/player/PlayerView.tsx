import { useEffect } from 'react'
import { leaveFullscreen, toggleFullscreen } from '../../player/fullscreen'
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
      // Only defer to real text entry. Range sliders (seek bar) and buttons
      // keep focus after a click; shortcuts must still work then.
      const t = e.target
      const isTextEntry =
        t instanceof HTMLTextAreaElement ||
        (t instanceof HTMLInputElement && !['range', 'checkbox', 'radio', 'button'].includes(t.type))
      if (isTextEntry) return
      switch (e.key) {
        case ' ':
          e.preventDefault()
          // Drop focus from whatever control was last clicked (button/slider),
          // so Space can't also activate it and immediately undo the toggle.
          if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
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
          void toggleFullscreen()
          break
        case 'ArrowUp':
          e.preventDefault()
          engine.nudgeVolume(0.05)
          break
        case 'ArrowDown':
          e.preventDefault()
          engine.nudgeVolume(-0.05)
          break
        case 'm':
          engine.setVolume(engine.getVolume() === 0 ? 1 : 0)
          break
        case '[':
          nudgeLyricOffset(-100)
          break
        case ']':
          nudgeLyricOffset(100)
          break
        case 'Escape':
          e.preventDefault()
          // Also drops the Electron window out of fullscreen, which the old
          // document.exitFullscreen() could not do.
          void leaveFullscreen()
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
      {song?.embedded_lyrics ? null : <SubtitleOverlay />}
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
