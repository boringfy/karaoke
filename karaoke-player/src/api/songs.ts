import { apiFetch, uploadFile } from './client'
import type {
  AudioTrack,
  JobInfo,
  Song,
  SongCreate,
  SongList,
  SubtitleDoc,
  UploadResult,
} from './types'

export interface ListParams {
  q?: string
  /** Exact artist match, unlike the fuzzy `q`. */
  artist?: string
  status?: string
  language?: string
  limit?: number
  offset?: number
}

export function listSongs(params: ListParams = {}): Promise<SongList> {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') qs.set(k, String(v))
  }
  const suffix = qs.toString() ? `?${qs}` : ''
  return apiFetch<SongList>(`/songs${suffix}`)
}

export function createSong(body: SongCreate): Promise<Song> {
  return apiFetch<Song>('/songs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function getSong(id: string): Promise<Song> {
  return apiFetch<Song>(`/songs/${id}`)
}

export function updateSong(id: string, body: Partial<SongCreate>): Promise<Song> {
  return apiFetch<Song>(`/songs/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function deleteSong(id: string): Promise<void> {
  return apiFetch<void>(`/songs/${id}`, { method: 'DELETE' })
}

export function uploadAudio(
  id: string,
  file: File,
  kind: AudioTrack,
  onProgress?: (fraction: number) => void,
): Promise<UploadResult> {
  return uploadFile<UploadResult>(`/songs/${id}/audio`, file, { kind }, onProgress)
}

export function uploadCover(
  id: string,
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<UploadResult> {
  return uploadFile<UploadResult>(`/songs/${id}/cover`, file, {}, onProgress)
}

export function uploadVideo(
  id: string,
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<UploadResult> {
  return uploadFile<UploadResult>(`/songs/${id}/video`, file, {}, onProgress)
}

export function separate(id: string, force = false): Promise<{ detail: string }> {
  return apiFetch(`/songs/${id}/separate?force=${force}`, { method: 'POST' })
}

export function reprocess(id: string, from = 'align'): Promise<{ detail: string }> {
  return apiFetch(`/songs/${id}/reprocess?from=${from}`, { method: 'POST' })
}

export function getSubtitle(id: string): Promise<SubtitleDoc> {
  return apiFetch<SubtitleDoc>(`/songs/${id}/subtitle?format=json`)
}

export function setSubtitleOffset(id: string, offsetMs: number): Promise<{ offset_ms: number }> {
  return apiFetch(`/songs/${id}/subtitle/offset`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ offset_ms: offsetMs }),
  })
}

export function getJobs(id: string): Promise<JobInfo[]> {
  return apiFetch<JobInfo[]>(`/songs/${id}/jobs`)
}
