import { API_BASE } from './client'
import type { AudioTrack } from './types'

export function audioUrl(songId: string, track: AudioTrack): string {
  return `${API_BASE}/songs/${songId}/audio?track=${track}`
}

export function videoUrl(songId: string): string {
  return `${API_BASE}/songs/${songId}/video`
}

export function subtitleUrl(songId: string, format = 'json'): string {
  return `${API_BASE}/songs/${songId}/subtitle?format=${format}`
}

/** version (e.g. song.updated_at) busts the <img> cache after a cover upload. */
export function coverUrl(songId: string, version?: string): string {
  const v = version ? `?v=${encodeURIComponent(version)}` : ''
  return `${API_BASE}/songs/${songId}/cover${v}`
}
