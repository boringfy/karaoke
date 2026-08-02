import { API_BASE } from './client'
import { getJobs, getSong } from './songs'
import type { SongEvent } from './types'

export interface SongEventsHandlers {
  onEvent: (ev: SongEvent) => void
  /** Called once processing reaches a terminal status (server sends `event: end`). */
  onEnd?: () => void
}

/**
 * Subscribe to a song's processing progress. Prefers SSE; falls back to
 * polling /jobs every 3s if the EventSource errors, and retries SSE after 15s.
 * Returns an unsubscribe function.
 */
export function subscribeSongEvents(songId: string, handlers: SongEventsHandlers): () => void {
  let closed = false
  let es: EventSource | null = null
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let retryTimer: ReturnType<typeof setTimeout> | null = null

  const stopPolling = () => {
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = null
  }

  const finish = () => {
    if (closed) return
    handlers.onEnd?.()
    close()
  }

  const startSse = () => {
    if (closed) return
    es = new EventSource(`${API_BASE}/songs/${songId}/events`)
    es.onmessage = (msg) => {
      stopPolling()
      try {
        handlers.onEvent(JSON.parse(msg.data) as SongEvent)
      } catch {
        // malformed frame — ignore
      }
    }
    es.addEventListener('end', () => finish())
    es.onerror = () => {
      es?.close()
      es = null
      if (closed) return
      startPolling()
      retryTimer = setTimeout(startSse, 15_000)
    }
  }

  const startPolling = () => {
    if (pollTimer || closed) return
    pollTimer = setInterval(async () => {
      try {
        const [song, jobs] = await Promise.all([getSong(songId), getJobs(songId)])
        handlers.onEvent({
          status: song.status,
          alignment_confidence: song.alignment_confidence,
          jobs: jobs.map((j) => ({ stage: j.stage, state: j.state, error: j.error })),
        })
        if (song.status !== 'processing' && song.status !== 'pending') finish()
      } catch {
        // server unreachable — keep trying
      }
    }, 3000)
  }

  const close = () => {
    closed = true
    es?.close()
    es = null
    stopPolling()
    if (retryTimer) clearTimeout(retryTimer)
  }

  startSse()
  return close
}
