import { create } from 'zustand'
import { onReachabilityChange } from '../api/client'

interface ServerState {
  /** null = not yet checked */
  reachable: boolean | null
  version: string | null
  setReachable: (reachable: boolean, version?: string | null) => void
}

export const useServerStore = create<ServerState>((set) => ({
  reachable: null,
  version: null,
  setReachable: (reachable, version = null) =>
    set((s) => ({ reachable, version: version ?? s.version })),
}))

// Any failed API call anywhere flips the app into the unreachable state.
onReachabilityChange((reachable) => {
  if (useServerStore.getState().reachable !== reachable) {
    useServerStore.getState().setReachable(reachable)
  }
})
