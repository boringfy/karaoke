import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import path from 'node:path'
import { startStaticServer } from './static-server'
import { startRemoteServer } from './remote-server'
import type { RemoteServerHandle, RemoteState } from './remote-server'
import { JsonStore } from './store'

const ALLOWED_PORTS = [5173, 3000] // must match karaoke-server CORS allowlist

let win: BrowserWindow | null = null

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (win) {
      if (win.isMinimized()) win.restore()
      win.focus()
    }
  })
}

async function resolveRendererUrl(): Promise<string> {
  const devUrl = process.env.VITE_DEV_SERVER_URL
  if (devUrl) return devUrl
  const rendererDir = path.join(app.getAppPath(), 'dist')
  const port = await startStaticServer(rendererDir, ALLOWED_PORTS)
  return `http://localhost:${port}`
}

async function createWindow() {
  let url: string
  try {
    url = await resolveRendererUrl()
  } catch (err) {
    dialog.showErrorBox(
      'Karaoke Player cannot start',
      `Ports ${ALLOWED_PORTS.join(' and ')} are in use by another application. ` +
        'Close it and relaunch. (A fixed port is required for the local karaoke-server to accept requests.)\n\n' +
        String(err),
    )
    app.quit()
    return
  }

  win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: '#0f1115',
    title: 'Karaoke Player',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  // Lock navigation to our own origin and the API host; open anything else externally.
  const isAllowed = (target: string) => {
    try {
      const u = new URL(target)
      return (
        (u.hostname === 'localhost' || u.hostname === '127.0.0.1') &&
        ['http:', 'ws:'].includes(u.protocol)
      )
    } catch {
      return false
    }
  }
  win.webContents.on('will-navigate', (event, target) => {
    if (!isAllowed(target)) {
      event.preventDefault()
      void shell.openExternal(target)
    }
  })
  win.webContents.setWindowOpenHandler(({ url: target }) => {
    if (!isAllowed(target)) void shell.openExternal(target)
    return { action: 'deny' }
  })

  await win.loadURL(url)
  // DevTools stay closed by default even in dev — this is a fullscreen media
  // app and a detached inspector steals focus on every launch. Open it on
  // demand with F12, or set KARAOKE_DEVTOOLS=1.
  if (process.env.VITE_DEV_SERVER_URL && process.env.KARAOKE_DEVTOOLS === '1') {
    win.webContents.openDevTools({ mode: 'detach' })
  }
  win.webContents.on('before-input-event', (_event, input) => {
    if (input.type === 'keyDown' && input.key === 'F12') {
      win?.webContents.toggleDevTools()
    }
  })
}

/** Latest state published by the renderer; served to remotes that connect
 * before the renderer has pushed an update. */
let remoteState: RemoteState = { playing: null, status: 'idle', queue: [], currentIndex: -1 }
let remote: RemoteServerHandle | null = null
/** karaoke-server base URL, published by the renderer so it cannot drift from
 * the constant the renderer itself uses. */
let serverBase = 'http://127.0.0.1:8787'

async function startRemote(store: JsonStore): Promise<void> {
  if (remote) return
  try {
    remote = await startRemoteServer(
      {
        getState: () => remoteState,
        command: (cmd) => win?.webContents.send('remote:command', cmd),
        search: async (q) => {
          const url = `${serverBase}/api/v1/songs?limit=25${q ? `&q=${encodeURIComponent(q)}` : ''}`
          const r = await fetch(url)
          if (!r.ok) throw new Error(`search failed: ${r.status}`)
          return await r.json()
        },
        cover: async (songId) => {
          // Reject anything that isn't a plain id before building a URL.
          if (!/^[a-zA-Z0-9_-]{1,64}$/.test(songId)) return null
          const r = await fetch(`${serverBase}/api/v1/songs/${songId}/cover`)
          if (!r.ok) return null
          return {
            body: Buffer.from(await r.arrayBuffer()),
            type: r.headers.get('content-type') ?? 'image/jpeg',
          }
        },
      },
      (await store.get('remoteToken')) as string | undefined,
    )
    void store.set('remoteToken', remote.token)
  } catch (err) {
    console.error('remote control server failed to start:', err)
  }
}

app.whenReady().then(() => {
  const store = new JsonStore()
  ipcMain.handle('store:get', (_e, key: string) => store.get(key))
  ipcMain.handle('store:set', (_e, key: string, value: unknown) => store.set(key, value))
  ipcMain.handle('remote:publish', (_e, state: RemoteState, base?: string) => {
    remoteState = state
    if (base) serverBase = base
    remote?.broadcast(state)
  })
  ipcMain.handle('remote:info', () =>
    remote ? { urls: remote.urls, token: remote.token, port: remote.port } : null,
  )
  void startRemote(store)
  ipcMain.handle('window:toggle-fullscreen', () => {
    if (win) win.setFullScreen(!win.isFullScreen())
  })
  ipcMain.handle('window:exit-fullscreen', () => {
    if (win?.isFullScreen()) win.setFullScreen(false)
  })

  void createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) void createWindow()
  })
})

app.on('window-all-closed', () => {
  app.quit()
})
