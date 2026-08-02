import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('karaoke', {
  store: {
    get: (key: string): Promise<unknown> => ipcRenderer.invoke('store:get', key),
    set: (key: string, value: unknown): Promise<void> => ipcRenderer.invoke('store:set', key, value),
  },
  toggleFullscreen: (): Promise<void> => ipcRenderer.invoke('window:toggle-fullscreen'),
  platform: process.platform,
})
