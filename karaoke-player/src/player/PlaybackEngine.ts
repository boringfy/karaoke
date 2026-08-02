import { audioUrl, videoUrl } from '../api/media'
import type { AudioTrack, Song } from '../api/types'

export type EngineStatus = 'idle' | 'loading' | 'playing' | 'paused' | 'ended' | 'error'

export interface EngineEvents {
  status: (status: EngineStatus) => void
  track: (track: AudioTrack) => void
  ended: () => void
  error: (message: string) => void
  loaded: (song: Song) => void
  durationchange: (duration: number) => void
}

const DRIFT_INTERVAL_MS = 500
const DRIFT_SOFT_S = 0.04 // below this: leave slave alone
const DRIFT_HARD_S = 0.25 // above this: hard resync
const SEEK_SETTLE_MS = 1000
const CROSSFADE_TAU_S = 0.02 // setTargetAtTime time constant (~60ms effective)
const LOAD_TIMEOUT_MS = 15_000

/**
 * Owns all media elements for the current song.
 *
 * Sync model: both audio tracks (when present) play *simultaneously*; the
 * active one is audible via its GainNode, the other is at gain 0. Toggling
 * tracks is a gain crossfade — no element ever seeks, so the swap is
 * position-perfect. The video is always muted and slaved to the master
 * audio clock with playbackRate nudges / hard resyncs.
 */
export class PlaybackEngine {
  readonly original: HTMLAudioElement
  readonly instrumental: HTMLAudioElement
  readonly video: HTMLVideoElement

  private ctx: AudioContext | null = null
  private gainOriginal: GainNode | null = null
  private gainInstrumental: GainNode | null = null

  private song: Song | null = null
  private status: EngineStatus = 'idle'
  private track: AudioTrack = 'instrumental'
  private loadToken = 0
  private driftTimer: ReturnType<typeof setInterval> | null = null
  private lastSeekAt = 0
  private listeners: { [K in keyof EngineEvents]: Set<EngineEvents[K]> } = {
    status: new Set(),
    track: new Set(),
    ended: new Set(),
    error: new Set(),
    loaded: new Set(),
    durationchange: new Set(),
  }

  constructor() {
    this.original = new Audio()
    this.instrumental = new Audio()
    this.video = document.createElement('video')
    for (const el of [this.original, this.instrumental, this.video]) {
      el.crossOrigin = 'anonymous'
      el.preload = 'auto'
    }
    this.video.muted = true
    this.video.playsInline = true

    this.original.addEventListener('ended', () => this.onMasterEnded(this.original))
    this.instrumental.addEventListener('ended', () => this.onMasterEnded(this.instrumental))
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') this.hardResyncSlaves()
    })
  }

  on<K extends keyof EngineEvents>(event: K, fn: EngineEvents[K]): () => void {
    this.listeners[event].add(fn)
    return () => this.listeners[event].delete(fn)
  }

  private emit<K extends keyof EngineEvents>(event: K, ...args: Parameters<EngineEvents[K]>) {
    for (const fn of this.listeners[event]) (fn as (...a: unknown[]) => void)(...args)
  }

  getSong(): Song | null {
    return this.song
  }

  getStatus(): EngineStatus {
    return this.status
  }

  getTrack(): AudioTrack {
    return this.track
  }

  /** Master clock element: instrumental when available, else original. */
  private get master(): HTMLAudioElement {
    if (this.song?.has_instrumental) return this.instrumental
    return this.original
  }

  /** True when the MV is much shorter than the audio and repeats. */
  private videoLoops = false

  private get slaves(): HTMLMediaElement[] {
    const out: HTMLMediaElement[] = []
    if (this.song?.has_instrumental && this.song?.has_original) {
      out.push(this.master === this.instrumental ? this.original : this.instrumental)
    }
    if (this.song?.has_video) out.push(this.video)
    return out
  }

  private get activeElements(): HTMLMediaElement[] {
    const out: HTMLMediaElement[] = []
    if (this.song?.has_original) out.push(this.original)
    if (this.song?.has_instrumental) out.push(this.instrumental)
    if (this.song?.has_video) out.push(this.video)
    return out
  }

  getTime(): number {
    return this.master.currentTime
  }

  getDuration(): number {
    const d = this.master.duration
    return Number.isFinite(d) ? d : (this.song?.duration_sec ?? 0)
  }

  canToggle(): boolean {
    return !!this.song?.has_original && !!this.song?.has_instrumental
  }

  private setStatus(status: EngineStatus) {
    if (this.status === status) return
    this.status = status
    this.emit('status', status)
  }

  async load(song: Song): Promise<void> {
    const token = ++this.loadToken
    this.stopDriftTimer()
    for (const el of [this.original, this.instrumental, this.video]) {
      el.pause()
      el.removeAttribute('src')
      el.load()
    }
    this.song = song
    this.setStatus('loading')

    const waits: Promise<void>[] = []
    if (song.has_original) {
      this.original.src = audioUrl(song.id, 'original')
      waits.push(this.waitCanPlay(this.original))
    }
    if (song.has_instrumental) {
      this.instrumental.src = audioUrl(song.id, 'instrumental')
      waits.push(this.waitCanPlay(this.instrumental))
    }
    if (song.has_video) {
      this.video.src = videoUrl(song.id)
      waits.push(this.waitCanPlay(this.video))
    }
    if (waits.length === 0) {
      this.setStatus('error')
      this.emit('error', 'This song has no audio yet.')
      return
    }

    try {
      await Promise.all(waits)
    } catch (err) {
      if (token !== this.loadToken) return // superseded by a newer load
      this.setStatus('error')
      this.emit('error', err instanceof Error ? err.message : 'Failed to load media')
      return
    }
    if (token !== this.loadToken) return

    // MV shorter than the audio (album track over a TV-size video): loop the
    // video when the audio is much longer (>1.5x), otherwise let it end and
    // freeze on the last frame while the audio plays out.
    this.videoLoops = false
    this.video.loop = false
    if (song.has_video) {
      const vd = this.video.duration
      if (Number.isFinite(vd) && vd > 0 && this.getDuration() > 1.5 * vd) {
        this.videoLoops = true
        this.video.loop = true
      }
    }

    // Default to instrumental (karaoke mode) when both tracks exist.
    this.track = song.has_instrumental ? 'instrumental' : 'original'
    this.applyGains(true)
    this.emit('track', this.track)
    this.emit('durationchange', this.getDuration())
    this.emit('loaded', song)
    this.setStatus('paused')
  }

  private waitCanPlay(el: HTMLMediaElement): Promise<void> {
    return new Promise((resolve, reject) => {
      if (el.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) {
        resolve()
        return
      }
      const timeout = setTimeout(() => {
        cleanup()
        reject(new Error('Timed out loading media (is karaoke-server running?)'))
      }, LOAD_TIMEOUT_MS)
      const onReady = () => {
        cleanup()
        resolve()
      }
      const onError = () => {
        cleanup()
        reject(new Error('Media failed to load'))
      }
      const cleanup = () => {
        clearTimeout(timeout)
        el.removeEventListener('canplay', onReady)
        el.removeEventListener('error', onError)
      }
      el.addEventListener('canplay', onReady)
      el.addEventListener('error', onError)
    })
  }

  /** Build the Web Audio graph lazily — must happen after a user gesture. */
  private ensureAudioGraph() {
    if (this.ctx) return
    try {
      this.ctx = new AudioContext()
      this.gainOriginal = this.ctx.createGain()
      this.gainInstrumental = this.ctx.createGain()
      this.ctx.createMediaElementSource(this.original).connect(this.gainOriginal)
      this.ctx.createMediaElementSource(this.instrumental).connect(this.gainInstrumental)
      this.gainOriginal.connect(this.ctx.destination)
      this.gainInstrumental.connect(this.ctx.destination)
      this.applyGains(true)
    } catch {
      // Web Audio unavailable — fall back to muting elements directly.
      this.ctx = null
    }
  }

  private applyGains(immediate: boolean) {
    const now = this.ctx?.currentTime ?? 0
    const wantOriginal = this.track === 'original' ? 1 : 0
    if (this.ctx && this.gainOriginal && this.gainInstrumental) {
      if (immediate) {
        this.gainOriginal.gain.cancelScheduledValues(now)
        this.gainInstrumental.gain.cancelScheduledValues(now)
        this.gainOriginal.gain.setValueAtTime(wantOriginal, now)
        this.gainInstrumental.gain.setValueAtTime(1 - wantOriginal, now)
      } else {
        this.gainOriginal.gain.setTargetAtTime(wantOriginal, now, CROSSFADE_TAU_S)
        this.gainInstrumental.gain.setTargetAtTime(1 - wantOriginal, now, CROSSFADE_TAU_S)
      }
      this.original.muted = false
      this.instrumental.muted = false
    } else {
      this.original.muted = wantOriginal === 0
      this.instrumental.muted = wantOriginal === 1
    }
  }

  async play(): Promise<void> {
    if (!this.song || this.status === 'loading' || this.status === 'idle') return
    this.ensureAudioGraph()
    if (this.ctx?.state === 'suspended') await this.ctx.resume()
    await Promise.all(
      this.activeElements.map((el) =>
        el.play().catch(() => {
          // A slave that fails to start will be caught by drift correction;
          // a master failure surfaces via status below.
        }),
      ),
    )
    this.startDriftTimer()
    this.setStatus('playing')
  }

  pause(): void {
    for (const el of this.activeElements) el.pause()
    this.stopDriftTimer()
    if (this.status === 'playing') this.setStatus('paused')
  }

  async togglePlay(): Promise<void> {
    if (this.status === 'playing') this.pause()
    else await this.play()
  }

  seekTo(t: number): void {
    if (!this.song) return
    const clamped = Math.min(Math.max(t, 0), this.getDuration() || t)
    this.lastSeekAt = performance.now()
    for (const el of this.activeElements) {
      el.currentTime = el === this.video ? this.videoTargetTime(clamped) : clamped
    }
    if (this.status === 'playing') {
      // A slave that had ended (frozen MV) stays paused after a seek back;
      // kick it so the picture moves again.
      for (const el of this.activeElements) {
        if (el.paused) void el.play().catch(() => undefined)
      }
    }
    if (this.status === 'ended') this.setStatus('paused')
  }

  /** Where the MV should be for audio time `t` (modulo when looping, clamped
   * to the final frame otherwise). */
  private videoTargetTime(t: number): number {
    const vd = this.video.duration
    if (!Number.isFinite(vd) || vd <= 0) return t
    if (this.videoLoops) return t % vd
    return Math.min(t, vd)
  }

  seekBy(delta: number): void {
    this.seekTo(this.getTime() + delta)
  }

  restart(): void {
    this.seekTo(0)
    void this.play()
  }

  setTrack(track: AudioTrack): void {
    if (!this.canToggle() || track === this.track) return
    this.track = track
    this.applyGains(false)
    this.emit('track', track)
  }

  toggleTrack(): void {
    this.setTrack(this.track === 'original' ? 'instrumental' : 'original')
  }

  private onMasterEnded(el: HTMLAudioElement) {
    if (el !== this.master) return
    this.pause()
    this.setStatus('ended')
    this.emit('ended')
  }

  private startDriftTimer() {
    this.stopDriftTimer()
    this.driftTimer = setInterval(() => this.correctDrift(), DRIFT_INTERVAL_MS)
  }

  private stopDriftTimer() {
    if (this.driftTimer) clearInterval(this.driftTimer)
    this.driftTimer = null
  }

  private correctDrift() {
    if (this.status !== 'playing') return
    if (performance.now() - this.lastSeekAt < SEEK_SETTLE_MS) return
    const masterTime = this.master.currentTime
    for (const slave of this.slaves) {
      if (slave.ended) continue // MV shorter than audio (no loop): freeze last frame
      const isLoopingVideo = slave === this.video && this.videoLoops
      const target = isLoopingVideo ? this.videoTargetTime(masterTime) : masterTime
      let delta = slave.currentTime - target
      if (isLoopingVideo) {
        // Wrap-around distance: video at 0.1s vs target 179.9s is 0.2s apart,
        // not 179.8 — never hard-resync across the loop seam.
        const vd = this.video.duration
        if (delta > vd / 2) delta -= vd
        else if (delta < -vd / 2) delta += vd
      }
      if (Math.abs(delta) <= DRIFT_SOFT_S) {
        if (slave.playbackRate !== 1) slave.playbackRate = 1
      } else if (Math.abs(delta) <= DRIFT_HARD_S) {
        slave.playbackRate = 1 - Math.min(Math.max(delta * 0.5, -0.04), 0.04)
      } else {
        slave.currentTime = target
        slave.playbackRate = 1
        if (slave.paused) void slave.play().catch(() => undefined)
      }
    }
  }

  private hardResyncSlaves() {
    if (this.status !== 'playing') return
    const masterTime = this.master.currentTime
    for (const slave of this.slaves) {
      if (slave.ended) continue
      const target = slave === this.video ? this.videoTargetTime(masterTime) : masterTime
      if (Math.abs(slave.currentTime - target) > DRIFT_SOFT_S) {
        slave.currentTime = target
      }
    }
  }

  /** Fully stop and release the current song (keeps the engine reusable). */
  unload(): void {
    this.loadToken++
    this.stopDriftTimer()
    for (const el of [this.original, this.instrumental, this.video]) {
      el.pause()
      el.removeAttribute('src')
      el.load()
    }
    this.song = null
    this.setStatus('idle')
  }
}

export const engine = new PlaybackEngine()
