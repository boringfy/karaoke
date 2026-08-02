import { app } from 'electron'
import fs from 'node:fs'
import path from 'node:path'

/** Tiny JSON settings store in userData (queue persistence, preferences). */
export class JsonStore {
  private file: string
  private data: Record<string, unknown>

  constructor(name = 'settings.json') {
    this.file = path.join(app.getPath('userData'), name)
    this.data = {}
    try {
      this.data = JSON.parse(fs.readFileSync(this.file, 'utf-8'))
    } catch {
      // first run or corrupt file — start empty
    }
  }

  get(key: string): unknown {
    return this.data[key] ?? null
  }

  set(key: string, value: unknown): void {
    this.data[key] = value
    try {
      fs.mkdirSync(path.dirname(this.file), { recursive: true })
      fs.writeFileSync(this.file, JSON.stringify(this.data, null, 2))
    } catch (err) {
      console.error('store write failed', err)
    }
  }
}
