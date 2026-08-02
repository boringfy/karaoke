import { setSubtitleOffset } from '../api/songs'
import { usePlayerStore } from '../stores/playerStore'
import { useUiStore } from '../stores/uiStore'

const MAX_OFFSET_MS = 60_000
const SAVE_DEBOUNCE_MS = 800

let saveTimer: ReturnType<typeof setTimeout> | null = null

/**
 * Shift lyric timing for the current song. Applies instantly in the overlay
 * (positive = subtitles later) and persists to the server debounced, so
 * repeated key presses coalesce into one PATCH.
 */
export function nudgeLyricOffset(deltaMs: number): void {
  const { song, subtitle } = usePlayerStore.getState()
  if (!song || !subtitle) return
  const next = Math.min(
    Math.max(subtitle.offset_ms + deltaMs, -MAX_OFFSET_MS),
    MAX_OFFSET_MS,
  )
  usePlayerStore.setState({ subtitle: { ...subtitle, offset_ms: next } })

  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    setSubtitleOffset(song.id, next).catch(() =>
      useUiStore.getState().toast('Could not save lyric sync to server', 'error'),
    )
  }, SAVE_DEBOUNCE_MS)
}
