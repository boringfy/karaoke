// pm2 process definition for karaoke-server.
// Start:   pm2 start ecosystem.config.cjs
// Reload:  pm2 reload karaoke-server
// Logs:    pm2 logs karaoke-server
module.exports = {
  apps: [
    {
      name: 'karaoke-server',
      // Run the venv's uvicorn directly (no shell), so the correct Python is used.
      script: '.venv/bin/python',
      args: '-m uvicorn karaoke_server.main:app --host 0.0.0.0 --port 8787',
      interpreter: 'none', // script is already an executable, not a node file
      cwd: __dirname,
      env: {
        // Persistent data dir (db + song files + model cache). Override as needed.
        KARAOKE_DATA_DIR: process.env.HOME + '/.local/share/karaoke-server',
        // Bind to all interfaces so LAN clients (e.g. the Android tablet app)
        // can reach it. This exposes the server to your local network — use a
        // trusted LAN. Set back to 127.0.0.1 for loopback-only.
        KARAOKE_HOST: '0.0.0.0',
        KARAOKE_PORT: '8787',
        // Keep separated vocal stems on disk: every re-alignment (lyric
        // change, refetch) then runs on the clean stem instead of the mix —
        // much better Whisper timing, and the quiet-intro gap recovery needs
        // the stem's VAD onset. Costs ~50-100MB disk per song.
        KARAOKE_KEEP_VOCAL_STEM: 'true',
      },
      autorestart: true,
      max_restarts: 10,
      // ML model loads can be slow on first run; give it room before "errored".
      min_uptime: '15s',
      restart_delay: 3000,
      kill_timeout: 10000,
      time: true, // timestamp log lines
    },
  ],
}
