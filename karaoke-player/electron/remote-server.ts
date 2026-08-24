import http from 'node:http'
import crypto from 'node:crypto'
import { remoteUiHtml, remoteManifest } from './remote-ui'

/**
 * LAN remote-control endpoint for the desktop player.
 *
 * Phones never talk to karaoke-server. They talk only to this server, which
 * relays commands to the renderer (the queue and playback engine live there)
 * and proxies library search / cover art on their behalf. That keeps exactly
 * one process holding a karaoke-server connection.
 *
 * State is pushed to clients over SSE rather than WebSocket: the flow is
 * server -> client only, and SSE needs no dependency beyond node:http.
 */

export interface RemoteState {
  playing: { id: string; title: string; artist: string | null } | null
  status: string
  queue: { songId: string; title: string; artist: string | null }[]
}

export type RemoteCommand =
  | { type: 'next' }
  | { type: 'enqueue'; songId: string }
  | { type: 'remove'; index: number }
  | { type: 'clear' }

export interface RemoteHooks {
  getState: () => RemoteState
  /** Relay a command to the renderer. */
  command: (cmd: RemoteCommand) => void
  /** Proxy a library search to karaoke-server (PC-side only). */
  search: (q: string) => Promise<unknown>
  /** Proxy cover art so the phone never contacts karaoke-server. */
  cover: (songId: string) => Promise<{ body: Buffer; type: string } | null>
}

export interface RemoteServerHandle {
  port: number
  token: string
  urls: string[]
  broadcast: (state: RemoteState) => void
  close: () => void
}

const DEFAULT_PORTS = [8790, 8791, 8792]

function json(res: http.ServerResponse, code: number, body: unknown) {
  const payload = JSON.stringify(body)
  res.writeHead(code, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
  })
  res.end(payload)
}

async function readJson(req: http.IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = []
  let size = 0
  for await (const c of req) {
    size += (c as Buffer).length
    // A control command is tiny; refuse anything that isn't.
    if (size > 64 * 1024) throw new Error('body too large')
    chunks.push(c as Buffer)
  }
  if (!chunks.length) return {}
  return JSON.parse(Buffer.concat(chunks).toString('utf8')) as Record<string, unknown>
}

/** Every LAN IPv4 address, so the UI can show a reachable URL. */
function lanUrls(port: number): string[] {
  const os = require('node:os') as typeof import('node:os')
  const out: string[] = []
  for (const addrs of Object.values(os.networkInterfaces())) {
    for (const a of addrs ?? []) {
      if (a.family === 'IPv4' && !a.internal) out.push(`http://${a.address}:${port}`)
    }
  }
  return out.length ? out : [`http://127.0.0.1:${port}`]
}

function listen(server: http.Server, ports: number[]): Promise<number> {
  return new Promise((resolve, reject) => {
    const tryPort = (i: number) => {
      if (i >= ports.length) {
        reject(new Error(`no free port among ${ports.join(', ')}`))
        return
      }
      server.once('error', () => tryPort(i + 1))
      // 0.0.0.0: the whole point is reachability from a phone on the LAN.
      server.listen(ports[i], '0.0.0.0', () => resolve(ports[i]))
    }
    tryPort(0)
  })
}

export async function startRemoteServer(
  hooks: RemoteHooks,
  existingToken?: string,
): Promise<RemoteServerHandle> {
  // Shared secret so a random device on the LAN cannot drive the player.
  const token = existingToken || crypto.randomBytes(16).toString('hex')
  const clients = new Set<http.ServerResponse>()

  const authed = (req: http.IncomingMessage, url: URL): boolean => {
    const supplied = url.searchParams.get('token') ?? req.headers['x-remote-token']
    const a = Buffer.from(String(supplied ?? ''))
    const b = Buffer.from(token)
    return a.length === b.length && crypto.timingSafeEqual(a, b)
  }

  const server = http.createServer((req, res) => {
    void (async () => {
      const url = new URL(req.url ?? '/', 'http://localhost')
      const p = url.pathname

      // The UI shell and manifest are unauthenticated: they contain no data
      // and the phone needs to load them before it can supply a token.
      if (p === '/' || p === '/index.html') {
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
        res.end(remoteUiHtml())
        return
      }
      if (p === '/manifest.webmanifest') {
        res.writeHead(200, { 'Content-Type': 'application/manifest+json' })
        res.end(remoteManifest())
        return
      }

      if (!authed(req, url)) {
        json(res, 401, { error: 'bad or missing token' })
        return
      }

      try {
        if (p === '/api/state' && req.method === 'GET') {
          json(res, 200, hooks.getState())
          return
        }

        if (p === '/api/events' && req.method === 'GET') {
          res.writeHead(200, {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            Connection: 'keep-alive',
          })
          res.write(`data: ${JSON.stringify(hooks.getState())}\n\n`)
          clients.add(res)
          // Comment frames keep proxies and dozing radios from dropping it.
          const ping = setInterval(() => res.write(': ping\n\n'), 25_000)
          req.on('close', () => {
            clearInterval(ping)
            clients.delete(res)
          })
          return
        }

        if (p === '/api/search' && req.method === 'GET') {
          json(res, 200, await hooks.search(url.searchParams.get('q') ?? ''))
          return
        }

        if (p.startsWith('/api/cover/') && req.method === 'GET') {
          const art = await hooks.cover(p.slice('/api/cover/'.length))
          if (!art) {
            res.writeHead(404)
            res.end()
            return
          }
          res.writeHead(200, { 'Content-Type': art.type, 'Cache-Control': 'max-age=3600' })
          res.end(art.body)
          return
        }

        if (req.method === 'POST') {
          const body = await readJson(req)
          switch (p) {
            case '/api/next':
              hooks.command({ type: 'next' })
              json(res, 200, { ok: true })
              return
            case '/api/queue/add':
              if (typeof body.songId !== 'string') {
                json(res, 400, { error: 'songId required' })
                return
              }
              hooks.command({ type: 'enqueue', songId: body.songId })
              json(res, 200, { ok: true })
              return
            case '/api/queue/remove':
              if (typeof body.index !== 'number') {
                json(res, 400, { error: 'index required' })
                return
              }
              hooks.command({ type: 'remove', index: body.index })
              json(res, 200, { ok: true })
              return
            case '/api/queue/clear':
              hooks.command({ type: 'clear' })
              json(res, 200, { ok: true })
              return
          }
        }

        json(res, 404, { error: 'not found' })
      } catch (err) {
        json(res, 500, { error: String(err) })
      }
    })()
  })

  const port = await listen(server, DEFAULT_PORTS)

  return {
    port,
    token,
    urls: lanUrls(port),
    broadcast(state) {
      const frame = `data: ${JSON.stringify(state)}\n\n`
      for (const c of clients) {
        try {
          c.write(frame)
        } catch {
          clients.delete(c)
        }
      }
    },
    close() {
      for (const c of clients) c.end()
      clients.clear()
      server.close()
    },
  }
}
