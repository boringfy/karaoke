import { useEffect, useState } from 'react'

const IDLE_MS = 2500

/**
 * True once the singer has been inactive for a moment, so the player chrome
 * (transport, back button, queue) can fade out and stop covering the video.
 *
 * Only hides while something is actually playing: when paused or loading the
 * controls are what the user is reaching for, and fading them out then would
 * mean waving the mouse to get them back.
 */
export function useIdleChrome(active: boolean): boolean {
  const [idle, setIdle] = useState(false)

  useEffect(() => {
    if (!active) {
      setIdle(false)
      return
    }
    let timer: ReturnType<typeof setTimeout>
    const wake = () => {
      setIdle(false)
      clearTimeout(timer)
      timer = setTimeout(() => setIdle(true), IDLE_MS)
    }
    // pointerdown/move covers mouse, pen and touch in one listener.
    const events = ['pointermove', 'pointerdown', 'keydown', 'wheel'] as const
    for (const e of events) window.addEventListener(e, wake, { passive: true })
    wake()
    return () => {
      clearTimeout(timer)
      for (const e of events) window.removeEventListener(e, wake)
    }
  }, [active])

  return idle
}
