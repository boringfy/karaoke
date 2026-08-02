import { useState } from 'react'
import { updateSong } from '../../api/songs'
import type { Language, Song } from '../../api/types'
import { useLibraryStore } from '../../stores/libraryStore'
import { useUiStore } from '../../stores/uiStore'

interface Props {
  song: Song
  onClose: () => void
}

export function EditSongDialog({ song, onClose }: Props) {
  const [title, setTitle] = useState(song.title)
  const [artist, setArtist] = useState(song.artist ?? '')
  const [album, setAlbum] = useState(song.album ?? '')
  const [language, setLanguage] = useState<Language>(song.language)
  const [saving, setSaving] = useState(false)
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
