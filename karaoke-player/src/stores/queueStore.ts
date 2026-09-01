import { create } from 'zustand'

export interface QueueItem {
  songId: string
  title: string
  artist: string | null
}

/**
 * The queue is a waiting list, not a history: a song leaves it the moment it
 * goes on stage, so the list is exactly who is still waiting. That is why
 * there is no pointer into it — the song being sung is playerStore's business.
 */
interface QueueState {
  queue: QueueItem[]
  add: (item: QueueItem) => void
  /** Append a whole list at once — one write, one persist, order preserved. */
  addAll: (items: QueueItem[]) => void
  removeAt: (index: number) => void
  clear: () => void
  /** Take one item off the list so it can go on stage; null if the index is stale. */
  takeAt: (index: number) => QueueItem | null
  /** Take the item at the front, or null when nobody is left waiting. */
  next: () => QueueItem | null
}

declare global {
  interface Window {
    karaoke?: {
      store: { get: (key: string) => Promise<unknown>; set: (key: string, value: unknown) => Promise<void> }
      toggleFullscreen: () => Promise<void>
      /** Optional: absent if the renderer is paired with an older preload. */
      exitFullscreen?: () => Promise<void>
      /** LAN remote control bridge; absent outside Electron. */
      remote?: {
        publish: (state: unknown, serverBase: string) => Promise<void>
        info: () => Promise<{ urls: string[]; token: string; port: number } | null>
        onCommand: (fn: (cmd: unknown) => void) => () => void
      }
      platform: string
    }
  }
}

const QUEUE_KEY = 'queue'

async function loadPersisted(): Promise<QueueItem[]> {
  try {
    if (window.karaoke) {
      const v = await window.karaoke.store.get(QUEUE_KEY)
      return Array.isArray(v) ? (v as QueueItem[]) : []
    }
    const raw = localStorage.getItem(QUEUE_KEY)
    return raw ? (JSON.parse(raw) as QueueItem[]) : []
  } catch {
    return []
  }
}

function persist(queue: QueueItem[]) {
  if (window.karaoke) {
    void window.karaoke.store.set(QUEUE_KEY, queue)
  } else {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(queue))
  }
}

export const useQueueStore = create<QueueState>((set, get) => ({
  queue: [],

  add: (item) => {
    const queue = [...get().queue, item]
    set({ queue })
    persist(queue)
  },

  addAll: (items) => {
    if (!items.length) return
    const queue = [...get().queue, ...items]
    set({ queue })
    persist(queue)
  },

  removeAt: (index) => {
    const queue = get().queue.filter((_, i) => i !== index)
    set({ queue })
    persist(queue)
  },

  clear: () => {
    set({ queue: [] })
    persist([])
  },

  takeAt: (index) => {
    const { queue } = get()
    const item = queue[index]
    if (!item) return null
    const rest = queue.filter((_, i) => i !== index)
    set({ queue: rest })
    persist(rest)
    return item
  },

  next: () => get().takeAt(0),
}))

void loadPersisted().then((queue) => {
  if (queue.length) useQueueStore.setState({ queue })
})
