import { useEffect, useState } from 'react'
import {
  createSong,
  getSong,
  reprocess,
  separate,
  uploadAudio,
  uploadCover,
  uploadVideo,
} from '../../api/songs'
import { refetchLyrics, uploadLyricsFile } from '../../api/lyrics'
import type { Language, Song } from '../../api/types'
import { useSongEvents } from '../../hooks/useSongEvents'
import { playSong } from '../../player/usePlaybackEngine'
import { useLibraryStore } from '../../stores/libraryStore'
import { useQueueStore } from '../../stores/queueStore'
import { useUiStore } from '../../stores/uiStore'
import { FileDrop } from './FileDrop'
import { JobProgress } from './JobProgress'

const AUDIO_ACCEPT = '.mp3,.flac,.wav,.m4a,.aac,.ogg,.opus,.wma,.aiff'
const VIDEO_ACCEPT = '.mp4,.mkv,.webm,.mov,.avi,.ts'
const IMAGE_ACCEPT = '.jpg,.jpeg,.png,.webp,.gif'

/**
 * Create song → upload audio (original / instrumental) → upload MV →
 * generate instrumental (optional) → watch processing → play.
 * Opening it for an existing song resumes at the files step.
 */
export function UploadWizard({ songId }: { songId: string | 'new' }) {
  const closeWizard = useUiStore((s) => s.closeWizard)
  const toast = useUiStore((s) => s.toast)
  const [song, setSong] = useState<Song | null>(null)
  const [title, setTitle] = useState('')
  const [artist, setArtist] = useState('')
  const [language, setLanguage] = useState<Language>('unknown')
  const [creating, setCreating] = useState(false)
  const [separating, setSeparating] = useState(false)

  const processing = song ? song.status === 'processing' || song.status === 'pending' : false
  const liveEvent = useSongEvents(song?.id ?? null, !!song)

  // Keep the song object fresh whenever the live status flips.
  useEffect(() => {
    if (!song || !liveEvent) return
    if (liveEvent.status !== song.status) {
      void getSong(song.id).then((s) => {
        setSong(s)
        useLibraryStore.getState().patchSong(s)
      })
    }
  }, [liveEvent, song])

  useEffect(() => {
    if (songId !== 'new') {
      void getSong(songId)
        .then(setSong)
        .catch(() => toast('Could not load song', 'error'))
    }
  }, [songId, toast])

  const refreshSong = async () => {
    if (!song) return
    const fresh = await getSong(song.id)
    setSong(fresh)
    useLibraryStore.getState().patchSong(fresh)
  }

  const create = async () => {
    setCreating(true)
    try {
      const created = await createSong({
        title: title.trim(),
        artist: artist.trim() || undefined,
        language,
      })
      setSong(created)
      void useLibraryStore.getState().refresh()
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setCreating(false)
    }
  }

  const generateInstrumental = async () => {
    if (!song) return
    setSeparating(true)
    try {
      await separate(song.id)
      await refreshSong()
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setSeparating(false)
    }
  }

  const playable = song && (song.status === 'ready' || song.status === 'needs_review')

  return (
    <div className="modal-backdrop" onClick={closeWizard}>
      <div className="modal modal--wide" onClick={(e) => e.stopPropagation()}>
        {!song ? (
          <>
            <h2>Add a new song</h2>
            <p className="hint">Create the song first — uploads are attached to it afterwards.</p>
            <label>
              Title *
              <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} />
            </label>
            <label>
              Singer
              <input value={artist} onChange={(e) => setArtist(e.target.value)} />
            </label>
            <label>
              Language
              <select value={language} onChange={(e) => setLanguage(e.target.value as Language)}>
                <option value="unknown">Auto-detect</option>
                <option value="en">English</option>
                <option value="zh">Chinese</option>
                <option value="ja">Japanese</option>
              </select>
            </label>
            <div className="modal-actions">
              <button onClick={closeWizard}>Cancel</button>
              <button className="primary" disabled={!title.trim() || creating} onClick={() => void create()}>
                {creating ? 'Creating…' : 'Create song'}
              </button>
            </div>
          </>
        ) : (
          <>
            <h2>
              {song.title}
              {song.artist ? <span className="modal-subtitle"> — {song.artist}</span> : null}
            </h2>

            <div className="wizard-grid">
              <FileDrop
                label="Original audio (with vocals)"
                hint="mp3 / flac / wav / m4a… — uploading starts lyric processing automatically"
                accept={AUDIO_ACCEPT}
                done={song.has_original}
                onFile={async (file, onProgress) => {
                  await uploadAudio(song.id, file, 'original', onProgress)
                  await refreshSong()
                }}
              />
              <FileDrop
                label="Instrumental audio (no vocals)"
                hint="Optional — or generate it from the original below"
                accept={AUDIO_ACCEPT}
                done={song.has_instrumental}
                onFile={async (file, onProgress) => {
                  await uploadAudio(song.id, file, 'instrumental', onProgress)
                  await refreshSong()
                }}
              />
              <FileDrop
                label="Music video (MV)"
                hint="Optional — mp4 / mkv / webm / mov…"
                accept={VIDEO_ACCEPT}
                done={song.has_video}
                onFile={async (file, onProgress) => {
                  await uploadVideo(song.id, file, onProgress)
                  await refreshSong()
                }}
              />
              <FileDrop
                label="Cover art"
                hint="Optional — jpg / png / webp; art embedded in the audio tags is used automatically"
                accept={IMAGE_ACCEPT}
                done={song.has_cover}
                onFile={async (file, onProgress) => {
                  await uploadCover(song.id, file, onProgress)
                  await refreshSong()
                }}
              />
              <FileDrop
                label="Lyrics file"
                hint={
                  song.has_original
                    ? 'Optional — .lrc or .txt; otherwise lyrics are found automatically. Uploading re-aligns subtitles.'
                    : 'Upload the original audio first — lyrics are aligned against it'
                }
                accept=".lrc,.txt"
                disabled={!song.has_original}
                done={song.has_lyrics}
                onFile={async (file) => {
                  await uploadLyricsFile(song.id, file)
                  toast('Lyrics uploaded — re-aligning subtitles…')
                  await refreshSong()
                }}
              />
            </div>

            {song.has_original && !song.has_instrumental ? (
              <div className="wizard-separate">
                <button className="primary" disabled={separating || processing} onClick={() => void generateInstrumental()}>
                  {separating ? 'Starting…' : 'Generate instrumental (remove vocals)'}
                </button>
                <span className="hint">Runs on the local server; takes a few minutes.</span>
              </div>
            ) : null}
            {song.has_instrumental && song.instrumental_source === 'generated' ? (
              <div className="hint">Instrumental was generated from the original.</div>
            ) : null}

            {song.has_original || song.has_instrumental ? (
              <div className="wizard-progress">
                <h3>
                  Processing
                  {song.status === 'ready' ? ' — done ✓' : null}
                  {song.status === 'failed' ? ' — failed' : null}
                  {song.status === 'needs_review' ? ' — check lyrics' : null}
                </h3>
                {processing ? <JobProgress event={liveEvent} /> : null}
                {song.status === 'needs_review' ? (
                  <div className="wizard-review">
                    <p>
                      Lyrics alignment confidence is low
                      {song.alignment_confidence != null
                        ? ` (${Math.round(song.alignment_confidence * 100)}%)`
                        : ''}
                      . The song is playable, but subtitles may drift.
                    </p>
                    <button
                      onClick={() => {
                        void refetchLyrics(song.id)
                          .then(() => refreshSong())
                          .catch((err) => toast(String(err.message ?? err), 'error'))
                      }}
                    >
                      Retry lyric search
                    </button>
                  </div>
                ) : null}
                {song.status === 'failed' ? (
                  <button
                    onClick={() => {
                      void reprocess(song.id)
                        .then(() => refreshSong())
                        .catch((err) => toast(String(err.message ?? err), 'error'))
                    }}
                  >
                    Retry processing
                  </button>
                ) : null}
              </div>
            ) : null}

            <div className="modal-actions">
              <button onClick={closeWizard}>Close</button>
              <button
                disabled={!playable}
                onClick={() => {
                  useQueueStore.getState().add({ songId: song.id, title: song.title, artist: song.artist })
                  toast(`Added "${song.title}" to queue`)
                }}
              >
                + Queue
              </button>
              <button
                className="primary"
                disabled={!playable}
                onClick={() => {
                  closeWizard()
                  void playSong(song)
                }}
              >
                ▶ Play now
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
