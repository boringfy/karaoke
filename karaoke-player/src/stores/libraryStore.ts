import { create } from 'zustand'
import { listSongs } from '../api/songs'
import type { Song } from '../api/types'

const PAGE_SIZE = 100

interface LibraryState {
  items: Song[]
  total: number
  q: string
  statusFilter: string
  /** Exact artist to browse, or '' for the whole library. */
  artistFilter: string
  offset: number
  loading: boolean
  error: string | null
  setQuery: (q: string) => void
  setStatusFilter: (status: string) => void
  setArtistFilter: (artist: string) => void
  setOffset: (offset: number) => void
  refresh: () => Promise<void>
  /** Patch a single song in place (e.g. after an SSE status update). */
  patchSong: (song: Song) => void
}

export const useLibraryStore = create<LibraryState>((set, get) => ({
  items: [],
  total: 0,
  q: '',
  statusFilter: '',
  artistFilter: '',
  offset: 0,
  loading: false,
  error: null,

  setQuery: (q) => {
    set({ q, offset: 0 })
    void get().refresh()
  },
  setStatusFilter: (statusFilter) => {
    set({ statusFilter, offset: 0 })
    void get().refresh()
  },
  setArtistFilter: (artistFilter) => {
    // Clearing the text search alongside it: a leftover query would silently
    // hide songs by the artist the user just asked to see.
    set({ artistFilter, q: artistFilter ? '' : get().q, offset: 0 })
    void get().refresh()
  },
  setOffset: (offset) => {
    set({ offset })
    void get().refresh()
  },

  refresh: async () => {
    const { q, statusFilter, artistFilter, offset } = get()
    set({ loading: true, error: null })
    try {
      const res = await listSongs({
        q: q || undefined,
        status: statusFilter || undefined,
        artist: artistFilter || undefined,
        limit: PAGE_SIZE,
        offset,
      })
      set({ items: res.items, total: res.total, loading: false })
    } catch (err) {
      set({ loading: false, error: err instanceof Error ? err.message : String(err) })
    }
  },

  patchSong: (song) =>
    set((s) => ({ items: s.items.map((it) => (it.id === song.id ? song : it)) })),
}))

export { PAGE_SIZE }
