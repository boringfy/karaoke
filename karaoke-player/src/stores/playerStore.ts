import { create } from 'zustand'
import type { AudioTrack, Song, SubtitleDoc } from '../api/types'
import type { EngineStatus } from '../player/PlaybackEngine'

interface PlayerState {
  song: Song | null
  status: EngineStatus
  track: AudioTrack
  duration: number
  /** Low-frequency time snapshot (~4 Hz) for non-smooth UI; smooth consumers
   * read engine.getTime() in their own rAF loop. */
  coarseTime: number
  subtitle: SubtitleDoc | null
  error: string | null
}

export const usePlayerStore = create<PlayerState>(() => ({
  song: null,
  status: 'idle',
  track: 'instrumental',
  duration: 0,
  coarseTime: 0,
  subtitle: null,
  error: null,
}))
