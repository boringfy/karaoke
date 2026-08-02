import { useState } from 'react'
import { playSongById } from '../../player/usePlaybackEngine'
import { useQueueStore } from '../../stores/queueStore'

export function QueuePanel() {
  const queue = useQueueStore((s) => s.queue)
  const currentIndex = useQueueStore((s) => s.currentIndex)
  const removeAt = useQueueStore((s) => s.removeAt)
  const clear = useQueueStore((s) => s.clear)
  const setCurrentIndex = useQueueStore((s) => s.setCurrentIndex)
  const [open, setOpen] = useState(false)

  return (
    <div className={`queue-panel ${open ? 'queue-panel--open' : ''}`}>
      <button className="queue-toggle" onClick={() => setOpen(!open)}>
        Queue ({queue.length})
      </button>
      {open ? (
        <div className="queue-list">
          {queue.length === 0 ? <div className="queue-empty">Queue is empty</div> : null}
          {queue.map((item, i) => (
            <div key={`${item.songId}-${i}`} className={`queue-item ${i === currentIndex ? 'queue-item--current' : ''}`}>
              <button
                className="queue-item-main"
                onClick={() => {
                  setCurrentIndex(i)
                  void playSongById(item.songId)
                }}
              >
                <span className="queue-item-title">{item.title}</span>
                {item.artist ? <span className="queue-item-artist">{item.artist}</span> : null}
              </button>
              <button className="queue-item-remove" title="Remove" onClick={() => removeAt(i)}>
                ×
              </button>
            </div>
          ))}
          {queue.length > 0 ? (
            <button className="link-btn" onClick={clear}>
              Clear queue
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
