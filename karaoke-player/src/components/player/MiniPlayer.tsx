import { useEffect, useRef, useState } from 'react'
import { coverUrl } from '../../api/media'
import type { SubtitleDoc } from '../../api/types'
import { engine } from '../../player/PlaybackEngine'
import { stopPlayback } from '../../player/usePlaybackEngine'
import { usePlayerStore } from '../../stores/playerStore'
import { useUiStore } from '../../stores/uiStore'
import { findLineIndex, lyricTime, tokenFill } from '../../subtitles/timing'
import { TokenLine } from '../../subtitles/TokenLine'

/** The current lyric line with live per-token fill — a compact reuse of the
 * full SubtitleOverlay for the mini-player. */
function MiniLyrics({ subtitle }: { subtitle: SubtitleDoc | null }) {
  const [idx, setIdx] = useState(-1)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!subtitle || subtitle.lines.length === 0) return
    let raf = 0
    let last = -2
    const frame = () => {
      const t = lyricTime(subtitle, engine.getTime())
      const i = findLineIndex(subtitle.lines, t)
      if (i !== last) {
        last = i
        setIdx(i)
      }
      if (i >= 0 && ref.current) {
        const tokens = subtitle.lines[i].tokens
        const spans = ref.current.querySelectorAll<HTMLElement>('.tok')
        for (let k = 0; k < spans.length && k < tokens.length; k++) {
          spans[k].style.setProperty('--fill', `${(tokenFill(tokens[k], t) * 100).toFixed(1)}%`)
        }
      }
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [subtitle])

  const line = idx >= 0 && subtitle ? subtitle.lines[idx] : null
  return (
    <div className="mini-lyric">
      {line ? (
        <TokenLine key={line.id} line={line} variant="current" ref={ref} />
      ) : (
        <span className="mini-lyric-idle">♪</span>
      )}
    </div>
  )
}

/**
 * Persistent mini-player shown over the library while a song is loaded, so the
 * lyrics keep scrolling and playback can be controlled (or stopped) without
 * returning to the full player.
 */
export function MiniPlayer() {
  const view = useUiStore((s) => s.view)
  const setView = useUiStore((s) => s.setView)
  const song = usePlayerStore((s) => s.song)
  const status = usePlayerStore((s) => s.status)
  const subtitle = usePlayerStore((s) => s.subtitle)

  // Only in the library, and only while a song is actually loaded.
  if (view === 'player' || !song || status === 'idle') return null

  return (
    <div className="mini-player" onClick={() => setView('player')}>
      {song.has_cover ? (
        <img className="mini-cover" src={coverUrl(song.id, song.updated_at)} alt="" />
      ) : (
        <div className="mini-cover mini-cover--placeholder">♪</div>
      )}
      <div className="mini-meta">
        <div className="mini-title">{song.title}</div>
        {song.artist ? <div className="mini-artist">{song.artist}</div> : null}
      </div>
      <MiniLyrics subtitle={subtitle} />
      <div className="mini-controls" onClick={(e) => e.stopPropagation()}>
        <button title={status === 'playing' ? 'Pause (space)' : 'Play'} onClick={() => void engine.togglePlay()}>
          {status === 'playing' ? '⏸' : '▶'}
        </button>
        <button title="Open full player" onClick={() => setView('player')}>
          ⤢
        </button>
        <button className="mini-stop" title="Stop" onClick={stopPlayback}>
          ⏹
        </button>
      </div>
    </div>
  )
}
