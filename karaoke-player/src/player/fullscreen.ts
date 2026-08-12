/** Fullscreen that works both under Electron and in a plain browser tab.
 *
 * Electron drives the real window through an IPC bridge, but that bridge only
 * exists when the preload script ran. Opened directly in a browser
 * (http://localhost:5173) `window.karaoke` is undefined, so fall back to the
 * Web Fullscreen API rather than silently doing nothing.
 *
 * The whole document is used as the fullscreen element, not the video, so the
 * subtitle overlay and transport stay composited on top.
 */

function browserFullscreenActive(): boolean {
  return document.fullscreenElement != null
}

export async function toggleFullscreen(): Promise<void> {
  if (window.karaoke) {
    await window.karaoke.toggleFullscreen()
    return
  }
  try {
    if (browserFullscreenActive()) await document.exitFullscreen()
    else await document.documentElement.requestFullscreen()
  } catch {
    // requestFullscreen rejects without a user gesture, and is unavailable in
    // some embedded contexts. Neither is worth surfacing to the singer.
  }
}

/** Leave fullscreen if we are in it; a no-op otherwise. Used on the way back
 * to the library so the app never strands the user in a fullscreen window. */
export async function leaveFullscreen(): Promise<void> {
  try {
    if (browserFullscreenActive()) {
      await document.exitFullscreen()
    } else if (window.karaoke) {
      // Electron owns the window state; ask it to drop out of fullscreen.
      await window.karaoke.exitFullscreen?.()
    }
  } catch {
    // ignore
  }
}
