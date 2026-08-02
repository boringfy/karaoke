import { create } from 'zustand'

export type View = 'library' | 'player'

interface Toast {
  id: number
  message: string
  kind: 'info' | 'error'
}

interface UiState {
  view: View
  /** Song id whose upload/processing wizard is open; 'new' = create step. */
  wizardSongId: string | null
  toasts: Toast[]
  setView: (view: View) => void
  openWizard: (songId: string | 'new') => void
  closeWizard: () => void
  toast: (message: string, kind?: 'info' | 'error') => void
  dismissToast: (id: number) => void
}

let toastSeq = 1

export const useUiStore = create<UiState>((set) => ({
  view: 'library',
  wizardSongId: null,
  toasts: [],
  setView: (view) => set({ view }),
  openWizard: (wizardSongId) => set({ wizardSongId }),
  closeWizard: () => set({ wizardSongId: null }),
  toast: (message, kind = 'info') => {
    const id = toastSeq++
    set((s) => ({ toasts: [...s.toasts, { id, message, kind }] }))
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
    }, 5000)
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))
