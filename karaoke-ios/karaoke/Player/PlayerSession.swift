import Foundation
import Observation
import SwiftUI

/// Owns the engine, the song on stage, and the sing-along queue. It lives above
/// the player screen so leaving the screen (down-chevron) keeps the song
/// playing under the library, the way the desktop mini-player does.
///
/// The queue is a waiting list: a song leaves it the moment it goes on stage,
/// so what remains is exactly what is still to be sung. It survives a restart,
/// so closing the app does not lose everyone's picks.
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
    var isPresentingPlayer = false

    private var api: APIClient?
    private var loadTask: Task<Void, Never>?
    private var offsetPush: Task<Void, Never>?

    private static let queueKey = "queue"

    init() {
        engine.onEnded = { [weak self] in self?.advance() }
        restoreQueue()
    }

    func configure(api: APIClient?) { self.api = api }

    var hasNext: Bool { !queue.isEmpty }
    var upNext: Song? { queue.first }

    // ---- queue -------------------------------------------------------------

    func playNow(_ song: Song) {
        isPresentingPlayer = true
        start(song)
    }

    /// Adds to the back of the list. With nothing on stage there is nobody to
    /// wait for, so the singing starts — from the top of the queue, which is
    /// not necessarily the song just added.
    func enqueue(_ song: Song) {
        queue.append(song)
        persistQueue()
        if current == nil {
            isPresentingPlayer = true
            advance()
        }
    }

    /// The library's "Play all": a whole list at once, keeping the order it
    /// was shown in. Same rule as `enqueue` — with nobody on stage the singing
    /// starts from the top of the queue.
    func enqueue(contentsOf songs: [Song]) {
        guard !songs.isEmpty else { return }
        queue.append(contentsOf: songs)
        persistQueue()
        if current == nil {
            isPresentingPlayer = true
            advance()
        }
    }

    /// Jump straight to a queued song. Like any song that reaches the stage it
    /// leaves the list; the ones it jumped ahead of keep their places.
    func playFromQueue(at index: Int) {
        guard queue.indices.contains(index) else { return }
        let song = queue.remove(at: index)
        persistQueue()
        isPresentingPlayer = true
        start(song)
    }

    func remove(at offsets: IndexSet) {
        queue.remove(atOffsets: offsets)
        persistQueue()
    }

    func move(from source: IndexSet, to destination: Int) {
        queue.move(fromOffsets: source, toOffset: destination)
        persistQueue()
    }

    func clearQueue() {
        queue.removeAll()
        persistQueue()
    }

    /// Take the next song off the front of the list and sing it; stop when the
    /// list runs out.
    func advance() {
        guard !queue.isEmpty else {
            isPresentingPlayer = false
            stop()
            return
        }
        let song = queue.removeFirst()
        persistQueue()
        start(song)
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
    }

    private func restoreQueue() {
        guard let data = UserDefaults.standard.data(forKey: Self.queueKey),
              let saved = try? JSONDecoder().decode([Song].self, from: data) else { return }
        // Whatever was on stage had already left the list, so the saved list is
        // exactly what is still waiting.
        queue = saved
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
