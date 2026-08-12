import { LibraryView } from './components/library/LibraryView'
import { PlayerView } from './components/player/PlayerView'
import { MiniPlayer } from './components/player/MiniPlayer'
import { ServerUnreachable } from './components/common/ServerUnreachable'
import { Toasts } from './components/common/Toasts'
import { UploadWizard } from './components/upload/UploadWizard'
import { useHealth } from './hooks/useHealth'
import { usePlaybackEngineBinding } from './player/usePlaybackEngine'
import { useRemoteControl } from './remote/useRemoteControl'
import { useServerStore } from './stores/serverStore'
import { useUiStore } from './stores/uiStore'

export default function App() {
  useHealth()
  usePlaybackEngineBinding()
  useRemoteControl()
  const reachable = useServerStore((s) => s.reachable)
  const view = useUiStore((s) => s.view)
  const wizardSongId = useUiStore((s) => s.wizardSongId)

  if (reachable === false) {
    return (
      <>
        <ServerUnreachable />
        <Toasts />
      </>
    )
  }

  return (
    <>
      {/* Keep the player mounted while browsing the library so audio continues. */}
      <div style={{ display: view === 'player' ? 'contents' : 'none' }}>
        <PlayerView />
      </div>
      {view === 'library' ? <LibraryView /> : null}
      <MiniPlayer />
      {wizardSongId ? <UploadWizard key={wizardSongId} songId={wizardSongId} /> : null}
      <Toasts />
    </>
  )
}
