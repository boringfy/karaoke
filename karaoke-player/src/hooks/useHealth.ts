import { useEffect } from 'react'
import { SERVER_BASE } from '../api/client'
import { useServerStore } from '../stores/serverStore'

const DOWN_POLL_MS = 3000
const UP_POLL_MS = 15_000

/** Polls GET /health — fast while down, relaxed while up. Mount once at App root. */
export function useHealth() {
  const reachable = useServerStore((s) => s.reachable)

  useEffect(() => {
    let cancelled = false
    const check = async () => {
      try {
        const res = await fetch(`${SERVER_BASE}/health`)
        const body = (await res.json()) as { status: string; version?: string }
        if (!cancelled) useServerStore.getState().setReachable(res.ok, body.version ?? null)
      } catch {
        if (!cancelled) useServerStore.getState().setReachable(false)
      }
    }
    void check()
    const timer = setInterval(check, reachable ? UP_POLL_MS : DOWN_POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [reachable])
}
