import { SERVER_BASE } from '../../api/client'

export function ServerUnreachable() {
  return (
    <div className="server-unreachable">
      <div className="server-unreachable-card">
        <h1>Waiting for karaoke-server…</h1>
        <p>
          The player cannot reach the local backend at <code>{SERVER_BASE}</code>.
        </p>
        <p>Start it in a terminal, e.g.:</p>
        <pre>karaoke-server</pre>
        <p className="hint">Retrying automatically every few seconds.</p>
      </div>
    </div>
  )
}
