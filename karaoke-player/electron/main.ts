import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import path from 'node:path'
import { startStaticServer } from './static-server'
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
  if (process.env.VITE_DEV_SERVER_URL) {
    win.webContents.openDevTools({ mode: 'detach' })
  }
}

app.whenReady().then(() => {
  const store = new JsonStore()
  ipcMain.handle('store:get', (_e, key: string) => store.get(key))
  ipcMain.handle('store:set', (_e, key: string, value: unknown) => store.set(key, value))
  ipcMain.handle('window:toggle-fullscreen', () => {
    if (win) win.setFullScreen(!win.isFullScreen())
  })

  void createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) void createWindow()
  })
})

app.on('window-all-closed', () => {
  app.quit()
})
