import { useEffect, useState } from 'react'
import type { Song } from '../../api/types'
import { PAGE_SIZE, useLibraryStore } from '../../stores/libraryStore'
import { useUiStore } from '../../stores/uiStore'
import { EditSongDialog } from './EditSongDialog'
import { RemoteControlCard } from './RemoteControlCard'
import { SearchBar } from './SearchBar'
import { SongRow } from './SongRow'

export function LibraryView() {
  const { items, total, offset, loading, error, artistFilter } = useLibraryStore()
  const refresh = useLibraryStore((s) => s.refresh)
  const setOffset = useLibraryStore((s) => s.setOffset)
  const setArtistFilter = useLibraryStore((s) => s.setArtistFilter)
  const openWizard = useUiStore((s) => s.openWizard)
  const [editing, setEditing] = useState<Song | null>(null)

  useEffect(() => {
    void refresh()
  }, [refresh])

  return (
    <div className="library-view">
      <header className="library-header">
        <h1>Karaoke Library</h1>
        <div className="library-header-actions">
          <SearchBar />
          <RemoteControlCard />
          <button className="primary" onClick={() => openWizard('new')}>
            + Add song
          </button>
        </div>
      </header>

      {artistFilter ? (
        <div className="filter-bar">
          <span className="filter-chip">
            <span className="filter-chip-label">Singer</span>
            <span className="filter-chip-value">{artistFilter}</span>
            <button
              type="button"
              aria-label="Clear singer filter"
              title="Show all singers"
              onClick={() => setArtistFilter('')}
            >
              ✕
            </button>
          </span>
          <span className="filter-count">
            {total} {total === 1 ? 'song' : 'songs'}
          </span>
        </div>
      ) : null}

      {error ? <div className="library-error">{error}</div> : null}

      <table className="song-table">
        <thead>
          <tr>
            <th>Song</th>
            <th>Length</th>
            <th>Status</th>
            <th>Assets</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {items.map((song) => (
            <SongRow key={song.id} song={song} onEdit={setEditing} />
          ))}
        </tbody>
      </table>

      {!loading && items.length === 0 ? (
        <div className="library-empty">
          <p>No songs yet.</p>
          <button className="primary" onClick={() => openWizard('new')}>
            Add your first song
          </button>
        </div>
      ) : null}

      {total > PAGE_SIZE ? (
        <div className="pagination">
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            ‹ Prev
          </button>
          <span>
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <button disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>
            Next ›
          </button>
        </div>
      ) : null}

      {editing ? <EditSongDialog song={editing} onClose={() => setEditing(null)} /> : null}
    </div>
  )
}
