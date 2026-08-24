import Foundation
import Observation
import SwiftUI

/// Owns the engine, the song on stage, and the sing-along queue. It lives above
/// the player screen so leaving the screen (down-chevron) keeps the song
/// playing under the library, the way the desktop mini-player does.
///
/// The queue follows the desktop's model: songs stay in the list and
/// `currentIndex` walks through them, rather than being consumed as they play.
/// A party wants to see what has been sung and what is coming, and to jump
/// around — and the list survives a restart.
@Observable
@MainActor
final class PlayerSession {
    let engine = PlaybackEngine()

    private(set) var current: Song?
    private(set) var subtitle: SubtitleDoc?
    /// Lyric nudge for the current song; mirrored to the server so every
    /// client sees the same timing.
    var offsetMs: Int = 0
    private(set) var queue: [Song] = []
    /// Position in `queue` of what is playing, or -1 when the current song was
    /// started straight from the library.
    private(set) var currentIndex: Int = -1
    var isPresentingPlayer = false

    private var api: APIClient?
    private var loadTask: Task<Void, Never>?
    private var offsetPush: Task<Void, Never>?

    private static let queueKey = "queue"
    private static let indexKey = "queue_index"

    init() {
        engine.onEnded = { [weak self] in self?.advance() }
        restoreQueue()
    }

    func configure(api: APIClient?) { self.api = api }

    /// Index of the song `advance()` would play next, clamped so a restored or
    /// emptied pointer can never address outside the list.
    private var nextIndex: Int { max(currentIndex, -1) + 1 }
    var hasNext: Bool { queue.indices.contains(nextIndex) }
    var upNext: Song? { hasNext ? queue[nextIndex] : nil }

    // ---- queue -------------------------------------------------------------

    func playNow(_ song: Song) {
        isPresentingPlayer = true
        currentIndex = -1        // started outside the queue
        start(song)
    }

    /// Adds to the list and nothing else. The play button plays; this one
    /// queues — a queue button that starts singing whenever the player happens
    /// to be idle is the same button twice.
    func enqueue(_ song: Song) {
        queue.append(song)
        persistQueue()
    }

    /// Jump straight to a queued song, leaving the rest of the list intact.
    func playFromQueue(at index: Int) {
        guard queue.indices.contains(index) else { return }
        currentIndex = index
        isPresentingPlayer = true
        start(queue[index])
    }

    func remove(at offsets: IndexSet) {
        // Keep the pointer on the same song as the desktop does: shift it down
        // for removals above it, and drop it when the playing item goes.
        for index in offsets.sorted(by: >) {
            if index < currentIndex { currentIndex -= 1 }
            else if index == currentIndex { currentIndex = -1 }
        }
        queue.remove(atOffsets: offsets)
        persistQueue()
    }

    func move(from source: IndexSet, to destination: Int) {
        let playing = queue.indices.contains(currentIndex) ? queue[currentIndex].id : nil
        queue.move(fromOffsets: source, toOffset: destination)
        if let playing { currentIndex = queue.firstIndex { $0.id == playing } ?? -1 }
        persistQueue()
    }

    func clearQueue() {
        queue.removeAll()
        currentIndex = -1
        persistQueue()
    }

    /// Step to the next queued song; stops when the list runs out.
    func advance() {
        let next = nextIndex
        guard queue.indices.contains(next) else {
            isPresentingPlayer = false
            stop()
            return
        }
        currentIndex = next
        start(queue[next])
    }

    func stop() {
        loadTask?.cancel()
        current = nil
        subtitle = nil
        Task { await engine.stop() }
    }

    // ---- lyric sync --------------------------------------------------------

    func nudgeOffset(_ deltaMs: Int) {
        guard let song = current else { return }
        offsetMs = max(-60_000, min(60_000, offsetMs + deltaMs))
        // Debounced: tapping the nudge five times should not fire five PATCHes.
        offsetPush?.cancel()
        let value = offsetMs
        offsetPush = Task { [api] in
            try? await Task.sleep(for: .milliseconds(600))
            guard !Task.isCancelled, let api else { return }
            try? await api.setSubtitleOffset(song.id, offsetMs: value)
        }
    }

    // ---- persistence -------------------------------------------------------

    private func persistQueue() {
        guard let data = try? JSONEncoder().encode(queue) else { return }
        UserDefaults.standard.set(data, forKey: Self.queueKey)
        UserDefaults.standard.set(currentIndex, forKey: Self.indexKey)
    }

    private func restoreQueue() {
        guard let data = UserDefaults.standard.data(forKey: Self.queueKey),
              let saved = try? JSONDecoder().decode([Song].self, from: data) else { return }
        queue = saved
        // Nothing is playing yet on a cold start, so the pointer sits just
        // before the song that was current when the app closed — and stays at
        // -1 when nothing was playing then either. Stepping back from -1 would
        // put it at -2, which reads as "up next: item 2" and sends advance()
        // into queue[-1].
        let savedIndex = (UserDefaults.standard.object(forKey: Self.indexKey) as? Int) ?? -1
        let clamped = min(max(savedIndex, -1), queue.count - 1)
        currentIndex = clamped >= 0 ? clamped - 1 : -1
    }

    // ---- internals ---------------------------------------------------------

    private func start(_ song: Song) {
        loadTask?.cancel()
        current = song
        subtitle = nil
        offsetMs = song.subtitleOffsetMs
        persistQueue()
        guard let api else { return }
        loadTask = Task {
            // Subtitles fetch in parallel with the media load; a song with
            // burned-in lyrics draws no overlay at all.
            async let subtitleFetch: SubtitleDoc? =
                (song.hasSubtitle && !song.embeddedLyrics) ? try? await api.subtitle(song.id) : nil
            await engine.load(api: api, song: song)
            let doc = await subtitleFetch
            guard !Task.isCancelled, current?.id == song.id else { return }
            subtitle = doc
            engine.play()
        }
    }
}
