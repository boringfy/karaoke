import { useEffect, useRef, useState } from 'react'
import { engine } from '../player/PlaybackEngine'
import { usePlayerStore } from '../stores/playerStore'
import { findLineIndex, findNextLineIndex, lyricTime, tokenFill } from './timing'
import { TokenLine } from './TokenLine'

/**
 * Karaoke overlay: current line with progressive per-token fill + upcoming line.
 * One rAF loop reads the engine clock; token fill is written straight to the
 * DOM via CSS vars so React only re-renders on line changes.
 */
export function SubtitleOverlay() {
  const subtitle = usePlayerStore((s) => s.subtitle)
  const status = usePlayerStore((s) => s.status)
  const [lineIdx, setLineIdx] = useState(-1)
  const [nextIdx, setNextIdx] = useState(-1)
  const currentLineRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!subtitle || subtitle.lines.length === 0) return
    let raf = 0
    let lastLine = -2 // force initial state sync

    const frame = () => {
      const t = lyricTime(subtitle, engine.getTime())
      const idx = findLineIndex(subtitle.lines, t)
      if (idx !== lastLine) {
        lastLine = idx
        setLineIdx(idx)
        setNextIdx(findNextLineIndex(subtitle.lines, t))
      }
      if (idx >= 0 && currentLineRef.current) {
        const tokens = subtitle.lines[idx].tokens
        const spans = currentLineRef.current.querySelectorAll<HTMLElement>('.tok')
        for (let i = 0; i < spans.length && i < tokens.length; i++) {
          spans[i].style.setProperty('--fill', `${(tokenFill(tokens[i], t) * 100).toFixed(1)}%`)
        }
      }
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [subtitle, status])

  if (!subtitle || subtitle.lines.length === 0) return null

  const current = lineIdx >= 0 ? subtitle.lines[lineIdx] : null
  const upcoming = nextIdx >= 0 ? subtitle.lines[nextIdx] : null

  return (
    <div className="subtitle-overlay">
      {current ? <TokenLine key={`c${current.id}`} line={current} variant="current" ref={currentLineRef} /> : null}
      {upcoming && upcoming !== current ? (
        <TokenLine key={`n${upcoming.id}`} line={upcoming} variant="next" />
      ) : null}
    </div>
  )
}
