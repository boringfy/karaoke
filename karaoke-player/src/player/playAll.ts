import { listSongs } from '../api/songs'
import type { ListParams } from '../api/songs'
import { usePlayerStore } from '../stores/playerStore'
import { useQueueStore } from '../stores/queueStore'
import { playNextInQueue } from './usePlaybackEngine'

/** The server's ceiling for one page; most libraries need a single trip. */
const PAGE = 500

/**
 * Queue every playable song the filters match, in the library's own order, and
 * start singing if the stage is empty.
 *
 * Shared by the library's "Play all" button and the phone remote, so a room
 * filled from either one gets the same list in the same order. Songs still
 * importing (or failed) are skipped rather than queued and skipped later.
 *
 * Returns how many songs were added.
 */
export async function queueAll(filters: ListParams = {}): Promise<number> {
  const songs = []
  for (let offset = 0; ; offset += PAGE) {
    const page = await listSongs({ ...filters, limit: PAGE, offset })
    songs.push(...page.items)
    if (!page.items.length || songs.length >= page.total) break
  }

  const items = songs
    .filter((s) => s.status === 'ready' || s.status === 'needs_review')
    .map((s) => ({ songId: s.id, title: s.title, artist: s.artist }))
  if (!items.length) return 0

  useQueueStore.getState().addAll(items)
  // "Play all", not "queue all": with nobody on stage the show starts now.
  if (!usePlayerStore.getState().song) void playNextInQueue()
  return items.length
}
