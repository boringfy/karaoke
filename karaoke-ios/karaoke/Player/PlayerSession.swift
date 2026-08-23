import Foundation
import Observation
import SwiftUI

/// Owns the engine, the song on stage, and the sing-along queue. It lives above
/// the player screen so leaving the screen (down-chevron) keeps the song
/// playing under the library, the way the desktop mini-player does.
@Observable
@MainActor
final class PlayerSession {
    let engine = PlaybackEngine()

    private(set) var current: Song?
    private(set) var subtitle: SubtitleDoc?
    /// Lyric nudge for the current song; mirrored to the server so every
    /// client sees the same timing.
    var offsetMs: Int = 0
    var queue: [Song] = []
    var isPresentingPlayer = false

    private var api: APIClient?
    private var loadTask: Task<Void, Never>?
    private var offsetPush: Task<Void, Never>?

    init() {
        engine.onEnded = { [weak self] in self?.advance() }
    }

    func configure(api: APIClient?) { self.api = api }

    // ---- queue -------------------------------------------------------------

    func playNow(_ song: Song) {
        isPresentingPlayer = true
        start(song)
    }

    func enqueue(_ song: Song) {
        // Nothing on stage yet: an "add" with an idle player just starts it.
        if current == nil {
            playNow(song)
        } else {
            queue.append(song)
        }
    }

    func remove(at offsets: IndexSet) { queue.remove(atOffsets: offsets) }
    func move(from source: IndexSet, to destination: Int) { queue.move(fromOffsets: source, toOffset: destination) }

    /// Skip to the next queued song; stops when the queue runs dry.
    func advance() {
        guard !queue.isEmpty else {
            isPresentingPlayer = false
            stop()
            return
        }
        start(queue.removeFirst())
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

    // ---- internals ---------------------------------------------------------

    private func start(_ song: Song) {
        loadTask?.cancel()
        current = song
        subtitle = nil
        offsetMs = song.subtitleOffsetMs
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
