import { create } from 'zustand'

export interface QueueItem {
  songId: string
  title: string
  artist: string | null
}

interface QueueState {
  queue: QueueItem[]
  /** Index of the currently playing item, -1 when nothing from the queue is playing. */
  currentIndex: number
  add: (item: QueueItem) => void
  removeAt: (index: number) => void
  clear: () => void
  setCurrentIndex: (index: number) => void
  /** Advance and return the next item, or null when exhausted. */
  next: () => QueueItem | null
}

declare global {
  interface Window {
    karaoke?: {
      store: { get: (key: string) => Promise<unknown>; set: (key: string, value: unknown) => Promise<void> }
      toggleFullscreen: () => Promise<void>
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
  currentIndex: -1,

  add: (item) => {
    const queue = [...get().queue, item]
    set({ queue })
    persist(queue)
  },

  removeAt: (index) => {
    const { queue, currentIndex } = get()
    const next = queue.filter((_, i) => i !== index)
    set({
      queue: next,
      currentIndex:
        index < currentIndex ? currentIndex - 1 : index === currentIndex ? -1 : currentIndex,
    })
    persist(next)
  },

  clear: () => {
    set({ queue: [], currentIndex: -1 })
    persist([])
  },

  setCurrentIndex: (currentIndex) => set({ currentIndex }),

  next: () => {
    const { queue, currentIndex } = get()
    const nextIndex = currentIndex + 1
    if (nextIndex >= queue.length) return null
    set({ currentIndex: nextIndex })
    return queue[nextIndex]
  },
}))

void loadPersisted().then((queue) => {
  if (queue.length) useQueueStore.setState({ queue })
})
