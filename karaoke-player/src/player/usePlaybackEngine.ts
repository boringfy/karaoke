import { useEffect } from 'react'
import { getSong, getSubtitle } from '../api/songs'
import type { Song } from '../api/types'
import { engine } from './PlaybackEngine'
import { usePlayerStore } from '../stores/playerStore'
import { useQueueStore } from '../stores/queueStore'
import { useUiStore } from '../stores/uiStore'

/** Load a song into the engine, fetch its subtitle, and start playback. */
export async function playSong(song: Song): Promise<void> {
  usePlayerStore.setState({ song, status: 'loading', subtitle: null, error: null, coarseTime: 0 })
  useUiStore.getState().setView('player')

  let subtitlePromise: Promise<void> = Promise.resolve()
  if (song.has_subtitle) {
    subtitlePromise = getSubtitle(song.id)
      .then((subtitle) => usePlayerStore.setState({ subtitle }))
      .catch(() => undefined)
  }
  await Promise.all([engine.load(song), subtitlePromise])
  if (engine.getSong()?.id === song.id && engine.getStatus() !== 'error') {
    await engine.play()
  }
}

/** Fully stop playback, release the song, and return to the library. */
export function stopPlayback(): void {
  engine.unload()
  usePlayerStore.setState({
    song: null,
    subtitle: null,
    status: 'idle',
    coarseTime: 0,
    error: null,
  })
  useUiStore.getState().setView('library')
}

/** Play a song by id (used by the queue, which stores ids only). */
export async function playSongById(songId: string): Promise<boolean> {
  try {
    const song = await getSong(songId)
    if (song.status !== 'ready' && song.status !== 'needs_review') {
      useUiStore.getState().toast(`"${song.title}" is not ready yet — skipped`, 'info')
      return false
    }
    await playSong(song)
    return true
  } catch {
    useUiStore.getState().toast('Song could not be loaded — skipped', 'error')
    return false
  }
}

export async function playNextInQueue(): Promise<void> {
  // Skip over items that are missing or not ready.
  for (;;) {
    const item = useQueueStore.getState().next()
    if (!item) {
      usePlayerStore.setState({ status: 'ended' })
      return
    }
    if (await playSongById(item.songId)) return
  }
}

/** Mount once (App root): mirrors engine events into playerStore, drives auto-advance. */
export function usePlaybackEngineBinding() {
  useEffect(() => {
    const offs = [
      engine.on('status', (status) => usePlayerStore.setState({ status })),
      engine.on('track', (track) => usePlayerStore.setState({ track })),
      engine.on('durationchange', (duration) => usePlayerStore.setState({ duration })),
      engine.on('error', (error) => usePlayerStore.setState({ error })),
      engine.on('ended', () => void playNextInQueue()),
    ]
    const coarseTimer = setInterval(() => {
      usePlayerStore.setState({ coarseTime: engine.getTime() })
    }, 250)
    return () => {
      offs.forEach((off) => off())
      clearInterval(coarseTimer)
    }
  }, [])
}
