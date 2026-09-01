import { useEffect, useState } from 'react'
import type { Song } from '../../api/types'
import { queueAll } from '../../player/playAll'
import { PAGE_SIZE, useLibraryStore } from '../../stores/libraryStore'
import { useUiStore } from '../../stores/uiStore'
import { QueuePanel } from '../player/QueuePanel'
import { EditSongDialog } from './EditSongDialog'
import { RemoteControlCard } from './RemoteControlCard'
import { SearchBar } from './SearchBar'
import { SongRow } from './SongRow'

export function LibraryView() {
  const { items, total, offset, loading, error, q, statusFilter, artistFilter } = useLibraryStore()
  const refresh = useLibraryStore((s) => s.refresh)
  const setOffset = useLibraryStore((s) => s.setOffset)
  const setArtistFilter = useLibraryStore((s) => s.setArtistFilter)
  const openWizard = useUiStore((s) => s.openWizard)
  const toast = useUiStore((s) => s.toast)
  const [editing, setEditing] = useState<Song | null>(null)
  const [queueingAll, setQueueingAll] = useState(false)

  /** Queue everything the current filters match — every page of it, not just
   * the one on screen — in the order the library lists it. */
  const onPlayAll = () => {
    setQueueingAll(true)
    queueAll({ q: q || undefined, status: statusFilter || undefined, artist: artistFilter || undefined })
      .then((n) => {
        if (n) toast(`Queued ${n} song${n === 1 ? '' : 's'}`)
        else toast('Nothing ready to queue yet')
      })
      .catch((err) => toast(err instanceof Error ? err.message : String(err), 'error'))
      .finally(() => setQueueingAll(false))
  }

  useEffect(() => {
    void refresh()
  }, [refresh])

  return (
    <div className="library-view">
      <header className="library-header">
        <h1>Karaoke Library</h1>
        <div className="library-header-actions">
          <SearchBar />
          <button onClick={onPlayAll} disabled={queueingAll || total === 0}>
            {queueingAll ? 'Queueing…' : '▶ Play all'}
          </button>
          <QueuePanel variant="inline" />
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
