import AVFoundation
import Combine
import SwiftUI
import UIKit

/// The singing screen, laid out like the desktop player: MV behind, lyrics over
/// it, and a transport bar rising out of a gradient — song meta on the left,
/// buttons in the middle, track toggle and lyric nudge on the right. The whole
/// bar fades while nobody is touching the iPad.
struct PlayerView: View {
    @Environment(AppConfig.self) private var config
    @Environment(PlayerSession.self) private var session

    @State private var position: Double = 0
    @State private var scrub: Double?
    @State private var chromeVisible = true
    @State private var hideTask: Task<Void, Never>?

    private let tick = Timer.publish(every: 0.2, on: .main, in: .common).autoconnect()

    private var engine: PlaybackEngine { session.engine }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            background.ignoresSafeArea()

            if let subtitle = session.subtitle {
                VStack {
                    Spacer()
                    LyricsCanvas(engine: engine, subtitle: subtitle, offsetMs: session.offsetMs)
                        .frame(height: 260)
                    Spacer().frame(height: 150)
                }
                .ignoresSafeArea()
            }

            if engine.isLoading {
                ProgressView().controlSize(.large).tint(Theme.textDim)
            }
            if let error = engine.loadError {
                Text(error)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Theme.danger)
                    .multilineTextAlignment(.center)
                    .padding(24)
            }

            VStack(spacing: 0) {
                topBar
                Spacer()
                transport
            }
            .opacity(chromeVisible ? 1 : 0)
            .animation(.easeInOut(duration: 0.22), value: chromeVisible)
        }
        .preferredColorScheme(.dark)
        .persistentSystemOverlays(chromeVisible ? .automatic : .hidden)
        .contentShape(Rectangle())
        .onTapGesture { showChrome() }
        .onReceive(tick) { _ in if scrub == nil { position = engine.positionSec } }
        .onAppear {
            UIApplication.shared.isIdleTimerDisabled = true
            showChrome()
        }
        .onDisappear {
            UIApplication.shared.isIdleTimerDisabled = false
            hideTask?.cancel()
        }
    }

    @ViewBuilder
    private var background: some View {
        if let video = engine.video {
            VideoLayerView(player: video)
        } else if let song = session.current, song.hasCover, let api = config.client {
            Theme.bg
                .overlay {
                    AsyncImage(url: api.coverURL(song)) { image in
                        image.resizable().scaledToFill()
                    } placeholder: { Color.clear }
                }
                .clipped()
                .blur(radius: 24)
                .overlay(Color.black.opacity(0.35))
        } else {
            Theme.bg
        }
    }

    // ---- chrome ------------------------------------------------------------

    private var topBar: some View {
        HStack(alignment: .top) {
            Button {
                // Leaving keeps the song playing, mini-player style.
                session.isPresentingPlayer = false
            } label: {
                Image(systemName: "chevron.down")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(Theme.text)
                    .frame(width: 40, height: 34)
                    .background(Color.white.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
            }
            .buttonStyle(.plain)
            Spacer()
            if let notice = engine.trackNotice {
                Text(notice)
                    .font(.system(size: 12))
                    .foregroundStyle(Theme.warn)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(Color.black.opacity(0.5))
                    .clipShape(Capsule())
            }
            Spacer()
            if !session.queue.isEmpty {
                VStack(alignment: .trailing, spacing: 2) {
                    Text("UP NEXT")
                        .font(.system(size: 10)).tracking(0.5)
                        .foregroundStyle(Theme.textDim)
                    Text(session.queue[0].displayTitle)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(Theme.text)
                        .lineLimit(1)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(Color.black.opacity(0.5))
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
        .padding(.horizontal, 24)
        .padding(.top, 16)
    }

    private var transport: some View {
        VStack(spacing: 10) {
            HStack(spacing: 10) {
                Text(Self.timecode(scrub ?? position))
                    .font(.system(size: 12).monospacedDigit())
                    .foregroundStyle(Theme.textDim)
                    .frame(minWidth: 36, alignment: .leading)
                Slider(
                    value: Binding(
                        get: { min(scrub ?? position, max(engine.duration, 0.001)) },
                        set: { scrub = $0 }),
                    in: 0...max(engine.duration, 0.001),
                    onEditingChanged: { editing in
                        if !editing, let value = scrub {
                            engine.seek(to: value)
                            position = value
                            scrub = nil
                        }
                        showChrome()
                    })
                .tint(Theme.accent)
                Text(Self.timecode(engine.duration))
                    .font(.system(size: 12).monospacedDigit())
                    .foregroundStyle(Theme.textDim)
                    .frame(minWidth: 36, alignment: .trailing)
            }

            HStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 1) {
                    Text(session.current?.displayTitle ?? "")
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(Theme.text)
                        .lineLimit(1)
                    Text(session.current?.displayArtist ?? "")
                        .font(.system(size: 12))
                        .foregroundStyle(Theme.textDim)
                        .lineLimit(1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                HStack(spacing: 8) {
                    button("gobackward", "Restart") { engine.restart() }
                    button("gobackward.10", "Back 10 seconds") { engine.seekBy(-10) }
                    Button {
                        engine.togglePlay()
                        showChrome()
                    } label: {
                        Image(systemName: engine.isPlaying ? "pause.fill" : "play.fill")
                            .font(.system(size: 18))
                            .foregroundStyle(Theme.text)
                            .frame(width: 48, height: 40)
                            .background(Color.white.opacity(0.08))
                            .clipShape(RoundedRectangle(cornerRadius: 6))
                    }
                    .buttonStyle(.plain)
                    button("goforward.10", "Forward 10 seconds") { engine.seekBy(10) }
                    button("forward.end.fill", "Next in queue") { session.advance() }
                        .disabled(session.queue.isEmpty)
                        .opacity(session.queue.isEmpty ? 0.45 : 1)
                }

                HStack(spacing: 10) {
                    Spacer(minLength: 0)
                    if engine.canToggle {
                        Picker("Track", selection: Binding(
                            get: { engine.track },
                            set: { engine.setTrack($0); showChrome() })) {
                            Text("Original").tag(AudioTrack.original)
                            Text("Karaoke").tag(AudioTrack.instrumental)
                        }
                        .pickerStyle(.segmented)
                        .frame(width: 200)
                    }
                    if session.subtitle != nil {
                        HStack(spacing: 6) {
                            button("minus", "Lyrics earlier") { session.nudgeOffset(-100) }
                            Text(String(format: "%@%.1fs",
                                        session.offsetMs > 0 ? "+" : "",
                                        Double(session.offsetMs) / 1000))
                                .font(.system(size: 12).monospacedDigit())
                                .foregroundStyle(Theme.textDim)
                                .frame(width: 46)
                            button("plus", "Lyrics later") { session.nudgeOffset(100) }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .trailing)
            }
        }
        .padding(.horizontal, 24)
        .padding(.top, 18)
        .padding(.bottom, 16)
        .background(
            LinearGradient(
                colors: [.clear, .black.opacity(0.85)],
                startPoint: .top, endPoint: .init(x: 0.5, y: 0.3))
            .allowsHitTesting(false))
    }

    private func button(_ symbol: String, _ label: String, action: @escaping () -> Void) -> some View {
        Button {
            action()
            showChrome()
        } label: {
            Image(systemName: symbol)
                .font(.system(size: 14))
                .foregroundStyle(Theme.text)
                .frame(width: 38, height: 34)
                .background(Color.white.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 6))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }

    /// Chrome must not cover the video (or the lyrics) all night, so it fades
    /// out a few seconds after the last touch.
    private func showChrome() {
        chromeVisible = true
        hideTask?.cancel()
        hideTask = Task {
            try? await Task.sleep(for: .seconds(4))
            guard !Task.isCancelled else { return }
            chromeVisible = false
        }
    }

    private static func timecode(_ seconds: Double) -> String {
        guard seconds.isFinite, seconds >= 0 else { return "0:00" }
        let total = Int(seconds.rounded())
        return String(format: "%d:%02d", total / 60, total % 60)
    }
}
