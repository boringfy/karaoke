import { useEffect, useRef, useState } from 'react'
import { engine } from '../../player/PlaybackEngine'
import { usePlayerStore } from '../../stores/playerStore'

function fmt(t: number): string {
  if (!Number.isFinite(t)) return '0:00'
  const m = Math.floor(t / 60)
  const s = Math.floor(t % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export function SeekBar() {
  const duration = usePlayerStore((s) => s.duration)
  const status = usePlayerStore((s) => s.status)
  const [dragValue, setDragValue] = useState<number | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const timeRef = useRef<HTMLSpanElement | null>(null)
  const dragging = dragValue !== null

  useEffect(() => {
    let raf = 0
    const frame = () => {
      const t = engine.getTime()
      if (!dragging && inputRef.current) inputRef.current.value = String(t)
      if (timeRef.current) timeRef.current.textContent = fmt(dragging ? dragValue : t)
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [dragging, dragValue, status])

  return (
    <div className="seekbar">
      <span className="seekbar-time" ref={timeRef}>
        0:00
      </span>
      <input
        ref={inputRef}
        className="seekbar-input"
        type="range"
        min={0}
        max={duration || 0}
        step={0.1}
        defaultValue={0}
        onInput={(e) => setDragValue(Number(e.currentTarget.value))}
        onPointerUp={(e) => {
          engine.seekTo(Number(e.currentTarget.value))
          setDragValue(null)
        }}
        onKeyDown={(e) => e.preventDefault()} // arrows are global shortcuts
      />
      <span className="seekbar-time">{fmt(duration)}</span>
    </div>
  )
}
