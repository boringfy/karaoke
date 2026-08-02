import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'

const MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.map': 'application/json',
}

/**
 * Serves the built renderer over http://127.0.0.1:<port> so the page origin
 * stays inside karaoke-server's CORS allowlist (localhost:5173 / localhost:3000).
 * Files are read through Electron's asar-aware fs.
 */
export function startStaticServer(rootDir: string, ports: number[]): Promise<number> {
  const root = path.resolve(rootDir)

  const server = http.createServer((req, res) => {
    const urlPath = decodeURIComponent((req.url ?? '/').split('?')[0])
    let filePath = path.normalize(path.join(root, urlPath))
    if (!filePath.startsWith(root)) {
      res.writeHead(403)
      res.end('Forbidden')
      return
    }
    if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
      // SPA fallback
      filePath = path.join(root, 'index.html')
    }
    const ext = path.extname(filePath).toLowerCase()
    res.writeHead(200, {
      'Content-Type': MIME[ext] ?? 'application/octet-stream',
      'Cache-Control': 'no-cache',
    })
    fs.createReadStream(filePath)
      .on('error', () => {
        res.destroy()
      })
      .pipe(res)
  })

  return new Promise((resolve, reject) => {
    // Resolve from the actual bound address: listen(port, cb) leaves the
    // callback of a failed attempt registered, so it must not close over the port.
    server.on('listening', () => {
      const addr = server.address()
      if (addr && typeof addr === 'object') resolve(addr.port)
      else reject(new Error('Static server bound to an unexpected address'))
    })
    const tryPort = (idx: number) => {
      if (idx >= ports.length) {
        reject(new Error(`Ports ${ports.join(', ')} are all in use`))
        return
      }
      server.once('error', (err: NodeJS.ErrnoException) => {
        if (err.code === 'EADDRINUSE') {
          tryPort(idx + 1)
        } else {
          reject(err)
        }
      })
      server.listen(ports[idx], '127.0.0.1')
    }
    tryPort(0)
  })
}
