import { useEffect, useState } from 'react'
import { subscribeSongEvents } from '../api/sse'
import { getSong } from '../api/songs'
import type { SongEvent } from '../api/types'
import { useLibraryStore } from '../stores/libraryStore'

/**
 * Live processing progress for one song. Also refreshes the library row
 * when processing reaches a terminal state.
 */
export function useSongEvents(songId: string | null, active: boolean): SongEvent | null {
  const [event, setEvent] = useState<SongEvent | null>(null)

  useEffect(() => {
    setEvent(null)
    if (!songId || !active) return
    const unsubscribe = subscribeSongEvents(songId, {
      onEvent: setEvent,
      onEnd: () => {
        void getSong(songId)
          .then((song) => useLibraryStore.getState().patchSong(song))
          .catch(() => undefined)
      },
    })
    return unsubscribe
  }, [songId, active])

  return event
}
