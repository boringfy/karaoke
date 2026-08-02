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
      args: '-m uvicorn karaoke_server.main:app --host 127.0.0.1 --port 8787',
      interpreter: 'none', // script is already an executable, not a node file
      cwd: __dirname,
      env: {
        // Persistent data dir (db + song files + model cache). Override as needed.
        KARAOKE_DATA_DIR: process.env.HOME + '/.local/share/karaoke-server',
        KARAOKE_HOST: '127.0.0.1',
        KARAOKE_PORT: '8787',
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
