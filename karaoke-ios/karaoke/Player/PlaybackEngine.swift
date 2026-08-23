import AVFoundation
import Foundation
import Observation

enum AudioTrack: String {
    case original, instrumental
}

/// Plays the original and instrumental tracks in parallel and crossfades their
/// gains, so switching to "karaoke" is seamless — no seek, no gap. The audible
/// track is the master clock; the silent track and the (muted) MV are pulled
/// back into sync when they drift. Mirrors the desktop and Flutter engines.
@Observable
@MainActor
final class PlaybackEngine {
    private let original = AVPlayer()
    private let instrumental = AVPlayer()
    /// Handed to the video layer view; nil when the song has no MV.
    private(set) var video: AVPlayer?

    private(set) var track: AudioTrack = .original
    private(set) var isPlaying = false
    private(set) var duration: Double = 0
    private(set) var isLoading = false
    private(set) var loadError: String?
    /// Set when a song loads in a degraded way (one track undecodable), so the
    /// player can say why the karaoke toggle is missing.
    private(set) var trackNotice: String?

    private var hasOriginal = false
    private var hasInstrumental = false
    /// MV much shorter than the audio: repeat it instead of freezing.
    private var videoLoops = false
    private var videoDuration: Double = 0
    private var videoOffsetSec: Double = 0

    private var driftTimer: Timer?
    /// Drift is ignored until this instant, so a correction is not immediately
    /// re-judged while the decoder is still catching up.
    private var videoSettledAt: Date = .distantPast
    private var fadeTimer: Timer?
    private var observers: [NSObjectProtocol] = []
    private var loadToken = 0

    /// An explicit toggle is a standing choice that carries to the next song.
    var trackPreference: AudioTrack = .original

    /// Fired when the master track reaches its end (queue auto-advance).
    var onEnded: (() -> Void)?

    var canToggle: Bool { hasOriginal && hasInstrumental }
    var hasMedia: Bool { hasOriginal || hasInstrumental }

    /// The audible track is the clock: the instrumental when both exist,
    /// otherwise whichever single track loaded.
    private var master: AVPlayer { hasInstrumental ? instrumental : original }
    private var audioPlayers: [AVPlayer] {
        (hasOriginal ? [original] : []) + (hasInstrumental ? [instrumental] : [])
    }

    var positionSec: Double {
        let t = master.currentTime().seconds
        return t.isFinite ? max(0, t) : 0
    }

    init() {
        for p in [original, instrumental] {
            // Required before setRate(_:time:atHostTime:), which is how both
            // tracks are started on the same host clock tick.
            p.automaticallyWaitsToMinimizeStalling = false
            p.volume = 0
        }
    }

    // ---- loading -----------------------------------------------------------

    func load(api: APIClient, song: Song) async {
        await reset()
        loadToken += 1
        let token = loadToken
        isLoading = true
        loadError = nil
        trackNotice = nil

        hasOriginal = song.hasOriginal
        hasInstrumental = song.hasInstrumental
        guard hasMedia else {
            isLoading = false
            loadError = "this song has no audio on the server"
            return
        }
        // Default to the standing original/karaoke choice; fall back to
        // whichever track actually exists.
        track = trackPreference
        if track == .original && !hasOriginal { track = .instrumental }
        if track == .instrumental && !hasInstrumental { track = .original }
        videoOffsetSec = Double(song.videoOffsetMs) / 1000

        if hasOriginal {
            original.replaceCurrentItem(with: AVPlayerItem(url: api.audioURL(song.id, track: "original")))
        }
        if hasInstrumental {
            instrumental.replaceCurrentItem(with: AVPlayerItem(url: api.audioURL(song.id, track: "instrumental")))
        }
        applyGains(immediate: true)

        if song.hasVideo {
            let p = AVPlayer(url: api.videoURL(song.id))
            p.automaticallyWaitsToMinimizeStalling = false
            p.isMuted = true // all audio comes from the audio players
            video = p
        }

        // Wait until every player can actually start, so the transport is not
        // live before the first frame/sample is there. A track the device
        // cannot decode (Opus, say) is dropped here rather than left in place
        // as a dead master clock that freezes the whole song at 0:00.
        if hasOriginal, await !Self.waitUntilReady(original) {
            hasOriginal = false
            original.replaceCurrentItem(with: nil)
        }
        if hasInstrumental, await !Self.waitUntilReady(instrumental) {
            hasInstrumental = false
            instrumental.replaceCurrentItem(with: nil)
        }
        guard hasMedia else {
            isLoading = false
            loadError = "This iPad can't play this song's audio format."
            return
        }
        if track == .instrumental && !hasInstrumental { track = .original }
        if track == .original && !hasOriginal { track = .instrumental }
        if !canToggle {
            trackNotice = hasInstrumental
                ? "Only the karaoke track is playable on iPad."
                : "Only the original track is playable on iPad — no karaoke mode for this song."
        }
        applyGains(immediate: true)
        if let v = video {
            // A video that won't load must degrade to audio-only playback,
            // never block the song.
            if await Self.waitUntilReady(v), let item = v.currentItem {
                let d = item.duration.seconds
                videoDuration = d.isFinite ? d : 0
            } else {
                video = nil
            }
        }
        guard token == loadToken else { return } // superseded by a newer load

        duration = audioPlayers
            .compactMap { $0.currentItem?.duration.seconds }
            .filter { $0.isFinite && $0 > 0 }
            .max() ?? (song.durationSec ?? 0)
        videoLoops = videoDuration > 0 && duration > 1.5 * videoDuration
        installEndObservers()
        isLoading = false
        if !hasMedia { loadError = "nothing to play" }
    }

    /// Polls `status` — simpler than KVO and the wait is bounded.
    private static func waitUntilReady(_ player: AVPlayer, timeout: Double = 20) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            switch player.currentItem?.status {
            case .readyToPlay: return true
            case .failed: return false
            default: try? await Task.sleep(for: .milliseconds(50))
            }
        }
        return false
    }

    // ---- transport ---------------------------------------------------------

    func play() {
        guard hasMedia, !isLoading else { return }
        isPlaying = true
        // Start every player on the same host-clock tick so the tracks (and the
        // MV) line up from the first sample instead of converging afterwards.
        videoRate = 1
        videoSettledAt = Date().addingTimeInterval(1.5)
        let host = CMClockGetTime(CMClockGetHostTimeClock())
            + CMTime(seconds: 0.15, preferredTimescale: 600)
        for p in audioPlayers { p.setRate(1, time: .invalid, atHostTime: host) }
        if let v = video, !(videoEnded(at: positionSec)) {
            v.setRate(1, time: .invalid, atHostTime: host)
        }
        startDrift()
    }

    func pause() {
        isPlaying = false
        videoRate = 1
        stopDrift()
        for p in audioPlayers { p.pause() }
        video?.pause()
    }

    func togglePlay() { isPlaying ? pause() : play() }

    func seek(to seconds: Double) {
        let clamped = max(0, duration > 0 ? min(seconds, duration) : seconds)
        let time = CMTime(seconds: clamped, preferredTimescale: 600)
        for p in audioPlayers {
            p.seek(to: time, toleranceBefore: .zero, toleranceAfter: .zero)
        }
        syncVideo(to: clamped, tolerance: 0.05, resume: true)
    }

    func seekBy(_ delta: Double) { seek(to: positionSec + delta) }

    func restart() {
        seek(to: 0)
        play()
    }

    func setTrack(_ t: AudioTrack) {
        guard canToggle, t != track else { return }
        track = t
        trackPreference = t
        applyGains(immediate: false)
    }

    func toggleTrack() { setTrack(track == .original ? .instrumental : .original) }

    /// Fully stop and release the current song; the engine stays reusable.
    func stop() async { await reset() }

    // ---- gains -------------------------------------------------------------

    private func applyGains(immediate: Bool) {
        // With only one track loaded it is always audible, whatever `track` says.
        let originalTarget: Float = canToggle ? (track == .original ? 1 : 0) : 1
        let instrumentalTarget: Float = canToggle ? (track == .instrumental ? 1 : 0) : 1
        fadeTimer?.invalidate()
        guard !immediate else {
            original.volume = hasOriginal ? originalTarget : 0
            instrumental.volume = hasInstrumental ? instrumentalTarget : 0
            return
        }
        let steps = 8
        let originalStart = original.volume, instrumentalStart = instrumental.volume
        var i = 0
        fadeTimer = Timer.scheduledTimer(withTimeInterval: 0.12 / Double(steps), repeats: true) { [weak self] timer in
            MainActor.assumeIsolated {
                guard let self else { return timer.invalidate() }
                i += 1
                let k = Float(min(1, Double(i) / Double(steps)))
                self.original.volume = originalStart + (originalTarget - originalStart) * k
                self.instrumental.volume = instrumentalStart + (instrumentalTarget - instrumentalStart) * k
                if i >= steps { timer.invalidate() }
            }
        }
    }

    // ---- A/V sync ----------------------------------------------------------

    /// Where the MV should be for audio time `t`. A positive video offset runs
    /// the picture ahead of the audio, so lyrics burned into it arrive earlier.
    private func videoTarget(for t: Double) -> Double {
        guard videoDuration > 0 else { return t }
        let shifted = t + videoOffsetSec
        if videoLoops { return shifted.truncatingRemainder(dividingBy: videoDuration) + (shifted < 0 ? videoDuration : 0) }
        return min(max(shifted, 0), videoDuration)
    }

    /// True once a non-looping MV is over but the audio keeps going — the last
    /// frame stays on screen by design.
    private func videoEnded(at t: Double) -> Bool {
        !videoLoops && videoDuration > 0 && t + videoOffsetSec >= videoDuration
    }

    /// Video seeks are always tolerant: an exact seek has to decode every frame
    /// from the preceding keyframe, which on a busy decoder costs more time
    /// than the drift it was correcting — the stutter feeds itself.
    private func syncVideo(to t: Double, tolerance: Double, resume: Bool) {
        guard let v = video else { return }
        if videoEnded(at: t) {
            v.seek(to: CMTime(seconds: max(0, videoDuration - 0.1), preferredTimescale: 600))
            v.pause()
            return
        }
        let target = CMTime(seconds: videoTarget(for: t), preferredTimescale: 600)
        let slack = CMTime(seconds: tolerance, preferredTimescale: 600)
        v.seek(to: target, toleranceBefore: slack, toleranceAfter: slack)
        videoRate = 1
        if resume && isPlaying { v.play() } // may have been frozen at the end
    }

    /// Keeps `video.rate` writes to a minimum — setting it every tick is itself
    /// enough to hitch playback.
    private var videoRate: Float = 1 {
        didSet {
            guard videoRate != oldValue, let v = video, isPlaying else { return }
            v.rate = videoRate
        }
    }

    private func startDrift() {
        stopDrift()
        // Gentle and infrequent: hard-seeking a streaming video on small drift
        // costs a rebuffer stutter, so only large drift is corrected.
        driftTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.correctDrift() }
        }
    }

    private func correctDrift() {
        guard isPlaying else { return }
        // A stalled or failed master reports a frozen time; correcting against
        // it would seek the MV back to the same spot every tick.
        guard master.currentItem?.status == .readyToPlay, master.rate > 0 else { return }
        let m = positionSec
        if canToggle {
            let other = hasInstrumental ? original : instrumental
            let delta = other.currentTime().seconds - m
            if delta.isFinite && abs(delta) > 0.4 {
                other.seek(to: CMTime(seconds: m, preferredTimescale: 600),
                           toleranceBefore: .zero, toleranceAfter: .zero)
            }
        }
        guard let v = video else { return }
        if videoEnded(at: m) { return }
        // After a jump, let the decoder settle instead of judging it mid-seek.
        guard Date() >= videoSettledAt else { return }
        let target = videoTarget(for: m)
        var delta = v.currentTime().seconds - target
        guard delta.isFinite else { return }
        if videoLoops && videoDuration > 0 {
            // Wrap-around distance: never seek across the loop seam.
            let half = videoDuration / 2
            if delta > half { delta -= videoDuration }
            if delta < -half { delta += videoDuration }
        }
        switch abs(delta) {
        case 1.2...:
            // Too far to walk back: jump, then stop judging for a moment.
            syncVideo(to: m, tolerance: 0.25, resume: false)
            videoSettledAt = Date().addingTimeInterval(2)
        case 0.15...:
            // Close enough to converge by running the picture a hair fast or
            // slow. Invisible to the eye, and it costs no decode work.
            videoRate = delta > 0 ? 0.97 : 1.03
        default:
            videoRate = 1
        }
    }

    private func stopDrift() {
        driftTimer?.invalidate()
        driftTimer = nil
    }

    // ---- end of item -------------------------------------------------------

    private func installEndObservers() {
        removeObservers()
        if let item = master.currentItem {
            observers.append(NotificationCenter.default.addObserver(
                forName: .AVPlayerItemDidPlayToEndTime, object: item, queue: .main
            ) { [weak self] _ in
                MainActor.assumeIsolated {
                    guard let self else { return }
                    self.isPlaying = false
                    self.stopDrift()
                    self.onEnded?()
                }
            })
        }
        if let v = video, let item = v.currentItem {
            observers.append(NotificationCenter.default.addObserver(
                forName: .AVPlayerItemDidPlayToEndTime, object: item, queue: .main
            ) { [weak self] _ in
                MainActor.assumeIsolated {
                    guard let self, self.videoLoops else { return }
                    v.seek(to: .zero)
                    if self.isPlaying { v.play() }
                }
            })
        }
    }

    private func removeObservers() {
        for o in observers { NotificationCenter.default.removeObserver(o) }
        observers.removeAll()
    }

    private func reset() async {
        isPlaying = false
        isLoading = false
        loadError = nil
        trackNotice = nil
        videoLoops = false
        videoDuration = 0
        videoOffsetSec = 0
        videoRate = 1
        videoSettledAt = .distantPast
        duration = 0
        stopDrift()
        fadeTimer?.invalidate()
        removeObservers()
        for p in [original, instrumental] {
            p.pause()
            p.replaceCurrentItem(with: nil)
            p.volume = 0
        }
        video?.pause()
        video?.replaceCurrentItem(with: nil)
        video = nil
        hasOriginal = false
        hasInstrumental = false
    }
}
