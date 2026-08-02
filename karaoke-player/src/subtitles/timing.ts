import type { SubtitleDoc, SubtitleLine, SubtitleToken } from '../api/types'

/**
 * Find the index of the line covering time t (seconds, already offset-adjusted),
 * or -1 when between/before lines. Lines are assumed sorted by start.
 */
export function findLineIndex(lines: SubtitleLine[], t: number): number {
  let lo = 0
  let hi = lines.length - 1
  let candidate = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (lines[mid].start <= t) {
      candidate = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  if (candidate >= 0 && t <= lines[candidate].end) return candidate
  return -1
}

/** Index of the first line starting after t, or -1 when none. */
export function findNextLineIndex(lines: SubtitleLine[], t: number): number {
  let lo = 0
  let hi = lines.length - 1
  let candidate = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (lines[mid].start > t) {
      candidate = mid
      hi = mid - 1
    } else {
      lo = mid + 1
    }
  }
  return candidate
}

/** Fill fraction [0,1] for one token at time t. */
export function tokenFill(tok: SubtitleToken, t: number): number {
  if (t <= tok.start) return 0
  if (t >= tok.end) return 1
  const span = tok.end - tok.start
  return span > 0 ? (t - tok.start) / span : 1
}

/** Playback time → lyric time, honoring the document's offset_ms. */
export function lyricTime(doc: SubtitleDoc, playbackTime: number): number {
  return playbackTime - doc.offset_ms / 1000
}
