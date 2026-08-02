import { apiFetch, uploadFile } from './client'
import type { LyricsCandidate } from './types'

export function getLyricsCandidates(songId: string): Promise<LyricsCandidate[]> {
  return apiFetch<LyricsCandidate[]>(`/songs/${songId}/lyrics/candidates`)
}

export function selectLyricsCandidate(songId: string, candidateId: string): Promise<unknown> {
  return apiFetch(`/songs/${songId}/lyrics/select`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ candidate_id: candidateId }),
  })
}

export function refetchLyrics(songId: string): Promise<unknown> {
  return apiFetch(`/songs/${songId}/lyrics/refetch`, { method: 'POST' })
}

export function uploadLyricsFile(songId: string, file: File): Promise<unknown> {
  return uploadFile(`/songs/${songId}/lyrics/upload`, file, {})
}
