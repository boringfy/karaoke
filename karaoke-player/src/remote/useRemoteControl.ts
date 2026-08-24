import { useEffect } from 'react'
import { SERVER_BASE } from '../api/client'
import { getSong } from '../api/songs'
import { playNextInQueue } from '../player/usePlaybackEngine'
import { usePlayerStore } from '../stores/playerStore'
import { useQueueStore } from '../stores/queueStore'

/**
 * Renderer half of the LAN remote control.
 *
 * The queue and the playback engine live here, so the Electron main process
 * cannot answer a remote on its own: this hook publishes state upward and
 * applies commands coming back down. Phones therefore drive the same stores
 * the desktop UI does, and the two can never disagree.
 *
 * No-op outside Electron — a browser tab has no main process to talk to.
 */

interface RemoteCommand {
  type: 'next' | 'enqueue' | 'remove' | 'clear'
  songId?: string
  index?: number
}

function snapshot() {
  const { song, status } = usePlayerStore.getState()
  const { queue } = useQueueStore.getState()
  return {
    playing: song ? { id: song.id, title: song.title, artist: song.artist } : null,
    status,
    queue: queue.map((q) => ({ songId: q.songId, title: q.title, artist: q.artist })),
  }
}

export function useRemoteControl(): void {
  useEffect(() => {
    const bridge = window.karaoke?.remote
    if (!bridge) return

    // playerStore also carries coarseTime, which ticks ~4x/second. Publishing
    // on every store change would spam each connected phone with identical
    // frames, so only push when the remote-visible slice actually differs.
    let last = ''
    const publish = () => {
      const state = snapshot()
      const serialized = JSON.stringify(state)
      if (serialized === last) return
      last = serialized
      void bridge.publish(state, SERVER_BASE)
    }

    const offCommand = bridge.onCommand((raw) => {
      const cmd = raw as RemoteCommand
      const queue = useQueueStore.getState()
      switch (cmd.type) {
        case 'next':
          void playNextInQueue()
          break
        case 'enqueue':
          if (!cmd.songId) break
          // The remote sends only an id; resolve the display fields here so a
          // queue entry added by phone looks identical to one added on the PC.
          void getSong(cmd.songId)
            .then((s) => queue.add({ songId: s.id, title: s.title, artist: s.artist }))
            .catch(() => {})
          break
        case 'remove':
          if (typeof cmd.index === 'number') queue.removeAt(cmd.index)
          break
        case 'clear':
          queue.clear()
          break
      }
    })

    // Push on every relevant change, plus once now for remotes already waiting.
    const offPlayer = usePlayerStore.subscribe(publish)
    const offQueue = useQueueStore.subscribe(publish)
    publish()

    return () => {
      offCommand()
      offPlayer()
      offQueue()
    }
  }, [])
}
