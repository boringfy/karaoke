import { useEffect } from 'react'
import { getSong, getSubtitle } from '../api/songs'
import type { Song } from '../api/types'
import { engine } from './PlaybackEngine'
import { usePlayerStore } from '../stores/playerStore'
import { useQueueStore } from '../stores/queueStore'
import { useUiStore } from '../stores/uiStore'

const VOLUME_KEY = 'volume'
const TRACK_KEY = 'trackPreference'

/** Volume persists across restarts, matching how the queue is stored:
 * Electron's JSON store when available, localStorage in a browser. */
async function restoreVolume(): Promise<void> {
  try {
    const raw = window.karaoke
      ? await window.karaoke.store.get(VOLUME_KEY)
      : localStorage.getItem(VOLUME_KEY)
    const v = typeof raw === 'string' ? Number(raw) : typeof raw === 'number' ? raw : NaN
    if (Number.isFinite(v)) {
      engine.setVolume(v)
      usePlayerStore.setState({ volume: engine.getVolume() })
    }
  } catch {
    // keep the default of full volume
  }
}

function saveVolume(volume: number): void {
  if (window.karaoke) void window.karaoke.store.set(VOLUME_KEY, volume)
  else localStorage.setItem(VOLUME_KEY, String(volume))
}

/** The original/karaoke choice is a standing preference, so it outlives both
 * the current song and the current session. */
async function restoreTrackPreference(): Promise<void> {
  try {
    const raw = window.karaoke
      ? await window.karaoke.store.get(TRACK_KEY)
      : localStorage.getItem(TRACK_KEY)
    if (raw === 'original' || raw === 'instrumental') engine.setTrackPreference(raw)
  } catch {
    // keep the default of karaoke mode
  }
}

function saveTrackPreference(track: string): void {
  if (window.karaoke) void window.karaoke.store.set(TRACK_KEY, track)
  else localStorage.setItem(TRACK_KEY, track)
}

/** Load a song into the engine, fetch its subtitle, and start playback. */
export async function playSong(song: Song): Promise<void> {
  usePlayerStore.setState({ song, status: 'loading', subtitle: null, error: null, coarseTime: 0 })
  useUiStore.getState().setView('player')

  let subtitlePromise: Promise<void> = Promise.resolve()
  // A song whose MV carries its own lyrics keeps subtitle null, which also
  // silences the mini-player's lyric line. Checked even when has_subtitle is
  // true: the flag may have been set after the song was already aligned.
  if (song.has_subtitle && !song.embedded_lyrics) {
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
      engine.on('volume', (volume) => {
        usePlayerStore.setState({ volume })
        void saveVolume(volume)
      }),
      engine.on('trackpreference', (track) => saveTrackPreference(track)),
      engine.on('ended', () => void playNextInQueue()),
    ]
    void restoreVolume()
    void restoreTrackPreference()
    const coarseTimer = setInterval(() => {
      usePlayerStore.setState({ coarseTime: engine.getTime() })
    }, 250)
    return () => {
      offs.forEach((off) => off())
      clearInterval(coarseTimer)
    }
  }, [])
}
