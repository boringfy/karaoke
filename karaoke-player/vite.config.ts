import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import electron from 'vite-plugin-electron'

// Port must stay 5173 (or 3000): karaoke-server's CORS allowlist only
// contains those two localhost origins.
export default defineConfig({
  plugins: [
    react(),
    electron([
      {
        entry: 'electron/main.ts',
        vite: { build: { outDir: 'dist-electron', rollupOptions: { output: { format: 'cjs' } } } },
      },
      {
        entry: 'electron/preload.ts',
        onstart(args) {
          args.reload()
        },
        vite: { build: { outDir: 'dist-electron', rollupOptions: { output: { format: 'cjs' } } } },
      },
    ]),
  ],
  server: { port: 5173, strictPort: true },
  build: { outDir: 'dist' },
})
