import { useState } from 'react'
import { useDebouncedCallback } from '../../hooks/useDebounce'
import { useLibraryStore } from '../../stores/libraryStore'

export function SearchBar() {
  const setQuery = useLibraryStore((s) => s.setQuery)
  const statusFilter = useLibraryStore((s) => s.statusFilter)
  const setStatusFilter = useLibraryStore((s) => s.setStatusFilter)
  const [value, setValue] = useState('')
  const debouncedSearch = useDebouncedCallback((q: string) => setQuery(q), 300)

  return (
    <div className="search-bar">
      <input
        type="search"
        placeholder="Search by song or singer name…"
        value={value}
        onChange={(e) => {
          setValue(e.target.value)
          debouncedSearch(e.target.value.trim())
        }}
      />
      <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
        <option value="">All statuses</option>
        <option value="ready">Ready</option>
        <option value="processing">Processing</option>
        <option value="pending">Pending</option>
        <option value="needs_review">Needs review</option>
        <option value="failed">Failed</option>
      </select>
    </div>
  )
}
