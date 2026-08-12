import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('karaoke', {
  store: {
    get: (key: string): Promise<unknown> => ipcRenderer.invoke('store:get', key),
    set: (key: string, value: unknown): Promise<void> => ipcRenderer.invoke('store:set', key, value),
  },
  toggleFullscreen: (): Promise<void> => ipcRenderer.invoke('window:toggle-fullscreen'),
  exitFullscreen: (): Promise<void> => ipcRenderer.invoke('window:exit-fullscreen'),
  remote: {
    publish: (state: unknown, serverBase: string): Promise<void> =>
      ipcRenderer.invoke('remote:publish', state, serverBase),
    info: (): Promise<{ urls: string[]; token: string; port: number } | null> =>
      ipcRenderer.invoke('remote:info'),
    onCommand: (fn: (cmd: unknown) => void): (() => void) => {
      const handler = (_e: unknown, cmd: unknown) => fn(cmd)
      ipcRenderer.on('remote:command', handler)
      return () => ipcRenderer.off('remote:command', handler)
    },
  },
  platform: process.platform,
})
