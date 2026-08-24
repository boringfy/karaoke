import { useState } from 'react'
import { playSongById } from '../../player/usePlaybackEngine'
import { useQueueStore } from '../../stores/queueStore'

interface Props {
  /** 'overlay' floats over the video; 'inline' sits in the library header and
   * drops its list down like the other header popovers. */
  variant?: 'overlay' | 'inline'
}

export function QueuePanel({ variant = 'overlay' }: Props) {
  const queue = useQueueStore((s) => s.queue)
  const takeAt = useQueueStore((s) => s.takeAt)
  const removeAt = useQueueStore((s) => s.removeAt)
  const clear = useQueueStore((s) => s.clear)
  const [open, setOpen] = useState(false)

  return (
    <div className={`queue-panel queue-panel--${variant} ${open ? 'queue-panel--open' : ''}`}>
      <button className="queue-toggle" onClick={() => setOpen(!open)}>
        Queue ({queue.length})
      </button>
      {open ? (
        <div className="queue-list">
          {queue.length === 0 ? <div className="queue-empty">Queue is empty</div> : null}
          {queue.map((item, i) => (
            <div key={`${item.songId}-${i}`} className="queue-item">
              <button
                className="queue-item-main"
                title="Sing this now"
                onClick={() => {
                  // Reaching the stage takes it off the waiting list; the ones
                  // it jumped ahead of keep their places.
                  const taken = takeAt(i)
                  if (taken) void playSongById(taken.songId)
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
