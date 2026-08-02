#!/usr/bin/env bash
# Launch the Karaoke Player UI (production Electron build).
# Also best-effort ensures the karaoke-server pm2 service is running.
set -euo pipefail

# Resolve paths relative to this script so the launcher is machine-independent.
PLAYER_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
SERVER_DIR="$(cd "$PLAYER_DIR/../karaoke-server" 2>/dev/null && pwd || true)"
cd "$PLAYER_DIR"

# Make node/npm/pm2 available in a bare desktop-session env (nvm if present).
[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh"

# 1. Best-effort: make sure the backend is up (it's a pm2 service).
if command -v pm2 >/dev/null 2>&1 && [ -n "$SERVER_DIR" ]; then
  if ! pm2 describe karaoke-server >/dev/null 2>&1; then
    pm2 start "$SERVER_DIR/ecosystem.config.cjs" >/dev/null 2>&1 || true
  else
    pm2 restart karaoke-server --silent >/dev/null 2>&1 || true
  fi
fi

# 2. Make sure the UI is built (first run / after a pull).
if [ ! -f "$PLAYER_DIR/dist/index.html" ] || [ ! -f "$PLAYER_DIR/dist-electron/main.js" ]; then
  npm run build
fi

# 3. Launch the desktop app. --no-sandbox because the app may live on a
#    non-root-owned mount where chrome-sandbox isn't setuid.
exec "$PLAYER_DIR/node_modules/electron/dist/electron" "$PLAYER_DIR" --no-sandbox "$@"
