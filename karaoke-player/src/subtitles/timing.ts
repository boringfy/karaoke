import type { SubtitleDoc, SubtitleLine, SubtitleToken } from '../api/types'

/** How early an upcoming line may be shown (unfilled) before it is sung. */
export const PREVIEW_LEAD_S = 10

/**
 * Index of the line to DISPLAY at time t (seconds, already offset-adjusted),
 * or -1 when nothing should show. A line is displayed from
 * max(previous line's end, its start - PREVIEW_LEAD_S) until its end: short
 * gaps show the next line immediately, long breaks preview it 10 s ahead.
 * The wipe still starts exactly at the line's real start (tokens before
 * their start time render unfilled). Lines are assumed sorted by start.
 */
export function findLineIndex(lines: SubtitleLine[], t: number): number {
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].end <= t) continue // already finished
    const prevEnd = i > 0 ? lines[i - 1].end : Number.NEGATIVE_INFINITY
    const displayFrom = Math.max(prevEnd, lines[i].start - PREVIEW_LEAD_S)
    return t >= displayFrom ? i : -1
  }
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
