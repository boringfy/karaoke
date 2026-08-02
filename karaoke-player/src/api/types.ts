export type SongStatus = 'pending' | 'processing' | 'ready' | 'needs_review' | 'failed'
export type Language = 'en' | 'zh' | 'ja' | 'unknown'
export type AudioTrack = 'original' | 'instrumental'

export interface Song {
  id: string
  title: string
  artist: string | null
  album: string | null
  language: Language
  duration_sec: number | null
  status: SongStatus
  alignment_confidence: number | null
  instrumental_source: 'uploaded' | 'generated' | null
  /** Persisted lyric sync adjustment; also baked into the subtitle doc's offset_ms. */
  subtitle_offset_ms: number
  has_original: boolean
  has_instrumental: boolean
  has_video: boolean
  has_lyrics: boolean
  has_subtitle: boolean
  has_cover: boolean
  created_at: string
  updated_at: string
}

export interface SongList {
  total: number
  items: Song[]
}

export interface SongCreate {
  title: string
  artist?: string
  album?: string
  language?: Language
}

export interface SubtitleToken {
  text: string
  start: number
  end: number
  ruby?: string | null
  p?: number | null
}

export interface SubtitleLine {
  id: number | string
  start: number
  end: number
  text: string
  translation?: string | null
  score?: number | null
  alignment?: 'aligned' | 'interpolated'
  tokens: SubtitleToken[]
}

export interface SubtitleDoc {
  schema: number
  lang: string
  title: string | null
  artist: string | null
  offset_ms: number
  lines: SubtitleLine[]
}

export type JobState = 'queued' | 'running' | 'done' | 'failed' | 'skipped'

export interface JobInfo {
  id: string
  stage: string
  state: JobState
  progress: number | null
  error: string | null
  attempts: number
  created_at: string | null
  started_at: string | null
  finished_at: string | null
}

export interface SongEvent {
  status: SongStatus
  alignment_confidence: number | null
  jobs: { stage: string; state: JobState; error: string | null }[]
}

export interface UploadResult {
  song_id: string
  kind?: string
  path_name: string
  sha256: string
  enqueued_stages: string[]
}

export interface LyricsCandidate {
  id: string
  provider: string
  provider_track_id: string | null
  title: string | null
  artist: string | null
  duration_sec: number | null
  is_synced: boolean
  score: number | null
  selected: boolean
}
