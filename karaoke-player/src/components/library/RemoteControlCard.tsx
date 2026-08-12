import { useEffect, useState } from 'react'

interface RemoteInfo {
  urls: string[]
  token: string
  port: number
}

/**
 * Shows the address and pairing code a phone needs to drive the player.
 * Renders nothing outside Electron, where no remote server exists.
 */
export function RemoteControlCard() {
  const [info, setInfo] = useState<RemoteInfo | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const bridge = window.karaoke?.remote
    if (!bridge) return
    // The server binds asynchronously at startup; retry briefly rather than
    // showing nothing if the renderer wins the race.
    let cancelled = false
    let tries = 0
    const poll = () => {
      void bridge.info().then((v) => {
        if (cancelled) return
        if (v) setInfo(v)
        else if (++tries < 10) setTimeout(poll, 500)
      })
    }
    poll()
    return () => {
      cancelled = true
    }
  }, [])

  if (!info) return null

  return (
    <div className="remote-card">
      <button className="remote-toggle" onClick={() => setOpen((v) => !v)}>
        📱 Phone remote {open ? '▾' : '▸'}
      </button>
      {open ? (
        <div className="remote-body">
          <p className="remote-hint">
            Open this address on a phone on the same network, then enter the code.
          </p>
          <ul className="remote-urls">
            {info.urls.map((u) => (
              <li key={u}>
                <code>{u}</code>
              </li>
            ))}
          </ul>
          <div className="remote-token">
            <span className="remote-token-label">Pairing code</span>
            <code>{info.token}</code>
            <button onClick={() => void navigator.clipboard?.writeText(info.token)}>Copy</button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
