import { useRef, useState } from 'react'
import { getSong, separate, updateSong, uploadAudio, uploadCover } from '../../api/songs'
import type { Language, Song } from '../../api/types'
import { useLibraryStore } from '../../stores/libraryStore'
import { useUiStore } from '../../stores/uiStore'

const AUDIO_ACCEPT = '.mp3,.flac,.wav,.m4a,.aac,.ogg,.opus,.wma,.aiff'
const IMAGE_ACCEPT = '.jpg,.jpeg,.png,.webp,.gif'

interface Props {
  song: Song
  onClose: () => void
}

export function EditSongDialog({ song, onClose }: Props) {
  const [cur, setCur] = useState<Song>(song)
  const [title, setTitle] = useState(song.title)
  const [artist, setArtist] = useState(song.artist ?? '')
  const [album, setAlbum] = useState(song.album ?? '')
  const [language, setLanguage] = useState<Language>(song.language)
  const [saving, setSaving] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const origRef = useRef<HTMLInputElement>(null)
  const instRef = useRef<HTMLInputElement>(null)
  const coverRef = useRef<HTMLInputElement>(null)
  const toast = useUiStore((s) => s.toast)

  const save = async () => {
    setSaving(true)
    try {
      const updated = await updateSong(song.id, {
        title: title.trim(),
        artist: artist.trim() || undefined,
        album: album.trim() || undefined,
        language,
      })
      useLibraryStore.getState().patchSong(updated)
      onClose()
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setSaving(false)
    }
  }

  // After a media change, refresh the row and this dialog's state.
  const refresh = async (msg: string) => {
    toast(msg)
    const fresh = await getSong(song.id)
    setCur(fresh)
    useLibraryStore.getState().patchSong(fresh)
  }

  const replace = async (file: File, kind: 'original' | 'instrumental') => {
    setBusy(kind === 'original' ? 'Replacing audio…' : 'Replacing instrumental…')
    try {
      await uploadAudio(song.id, file, kind)
      await refresh(
        kind === 'original'
          ? 'Audio replaced — reprocessing lyrics & instrumental…'
          : 'Instrumental replaced',
      )
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setBusy(null)
    }
  }

  const replaceCover = async (file: File) => {
    setBusy('Uploading cover…')
    try {
      await uploadCover(song.id, file)
      await refresh('Cover updated (auto-scaled on the server)')
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setBusy(null)
    }
  }

  const regenerate = async () => {
    setBusy('Regenerating instrumental…')
    try {
      await separate(song.id, true) // force: replace whatever is there
      await refresh('Regenerating instrumental — watch progress in the library')
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setBusy(null)
    }
  }

  const pick = (ref: React.RefObject<HTMLInputElement | null>) => () => ref.current?.click()
  const onPicked =
    (kind: 'original' | 'instrumental') => (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (file) void replace(file, kind)
      e.target.value = ''
    }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Edit song</h2>
        <label>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label>
          Singer
          <input value={artist} onChange={(e) => setArtist(e.target.value)} />
        </label>
        <label>
          Album
          <input value={album} onChange={(e) => setAlbum(e.target.value)} />
        </label>
        <label>
          Language
          <select value={language} onChange={(e) => setLanguage(e.target.value as Language)}>
            <option value="unknown">Auto / unknown</option>
            <option value="en">English</option>
            <option value="zh">Chinese</option>
            <option value="ja">Japanese</option>
          </select>
        </label>

        <div className="edit-media">
          <h3>Audio</h3>
          <div className="edit-media-row">
            <span className="edit-media-name">
              Original {cur.has_original ? '✓' : '—'}
            </span>
            <button disabled={!!busy} onClick={pick(origRef)}>
              Replace audio…
            </button>
            <input ref={origRef} type="file" accept={AUDIO_ACCEPT} hidden onChange={onPicked('original')} />
          </div>
          <div className="edit-media-row">
            <span className="edit-media-name">
              Instrumental {cur.has_instrumental ? `✓ (${cur.instrumental_source ?? ''})` : '—'}
            </span>
            <button disabled={!!busy} onClick={pick(instRef)}>
              Replace…
            </button>
            <input ref={instRef} type="file" accept={AUDIO_ACCEPT} hidden onChange={onPicked('instrumental')} />
            <button disabled={!!busy || !cur.has_original} onClick={() => void regenerate()}>
              Regenerate
            </button>
          </div>
          <div className="edit-media-row">
            <span className="edit-media-name">Cover {cur.has_cover ? '✓' : '—'}</span>
            <button disabled={!!busy} onClick={() => coverRef.current?.click()}>
              Replace cover…
            </button>
            <input
              ref={coverRef}
              type="file"
              accept={IMAGE_ACCEPT}
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) void replaceCover(file)
                e.target.value = ''
              }}
            />
          </div>
          <span className="hint">
            {busy ?? 'Replacing the original re-runs lyric processing. Covers are auto-scaled.'}
          </span>
        </div>

        <div className="modal-actions">
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={saving || !title.trim()} onClick={() => void save()}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
