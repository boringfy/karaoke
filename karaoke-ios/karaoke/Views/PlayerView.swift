import AVFoundation
import Combine
import SwiftUI
import UIKit

/// The singing screen: MV (or cover art) behind, karaoke lyrics over it, and a
/// transport that fades away while nobody is touching the iPad.
struct PlayerView: View {
    @Environment(AppConfig.self) private var config
    @Environment(PlayerSession.self) private var session
    @Environment(\.dismiss) private var dismiss

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
            LinearGradient(
                colors: [.clear, .black.opacity(0.8)],
                startPoint: .center, endPoint: .bottom
            )
            .ignoresSafeArea()

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
                ProgressView().controlSize(.large).tint(.white)
            }
            if let error = engine.loadError {
                Text(error)
                    .font(.headline)
                    .foregroundStyle(.red)
                    .padding()
            }
            if let notice = engine.trackNotice {
                VStack {
                    Text(notice)
                        .font(.footnote)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 8)
                        .background(.ultraThinMaterial, in: Capsule())
                        .padding(.top, 90)
                    Spacer()
                }
                .opacity(chromeVisible ? 1 : 0)
                .animation(.easeInOut(duration: 0.35), value: chromeVisible)
            }

            VStack {
                topBar
                Spacer()
                transport
            }
            .opacity(chromeVisible ? 1 : 0)
            .animation(.easeInOut(duration: 0.35), value: chromeVisible)
        }
        .preferredColorScheme(.dark)
        .persistentSystemOverlays(chromeVisible ? .automatic : .hidden)
        .contentShape(Rectangle())
        .onTapGesture { showChrome() }
        .onReceive(tick) { _ in
            if scrub == nil { position = engine.positionSec }
        }
        .onAppear {
            UIApplication.shared.isIdleTimerDisabled = true
            showChrome()
        }
        .onDisappear {
            UIApplication.shared.isIdleTimerDisabled = false
            hideTask?.cancel()
        }
    }

    // ---- background --------------------------------------------------------

    @ViewBuilder
    private var background: some View {
        if let video = engine.video {
            VideoLayerView(player: video)
        } else if let song = session.current, song.hasCover, let api = config.client {
            Color(red: 0.06, green: 0.07, blue: 0.08)
                .overlay {
                    AsyncImage(url: api.coverURL(song)) { image in
                        image.resizable().scaledToFill()
                    } placeholder: {
                        Color.clear
                    }
                }
                .clipped()
                .blur(radius: 24)
            .overlay(Color.black.opacity(0.35))
        } else {
            Color(red: 0.06, green: 0.07, blue: 0.08)
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
                    .font(.title2.weight(.semibold))
                    .padding(12)
                    .background(.ultraThinMaterial, in: Circle())
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text(session.current?.displayTitle ?? "")
                    .font(.title3.weight(.semibold))
                Text(session.current?.displayArtist ?? "")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                if !session.queue.isEmpty {
                    Text("Next: \(session.queue[0].displayTitle)")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .padding(.horizontal, 24)
        .padding(.top, 16)
        .foregroundStyle(.white)
    }

    private var transport: some View {
        VStack(spacing: 12) {
            HStack(spacing: 12) {
                Text(Self.timecode(scrub ?? position))
                    .font(.caption.monospacedDigit())
                Slider(
                    value: Binding(
                        get: { min(scrub ?? position, max(engine.duration, 0.001)) },
                        set: { scrub = $0 }
                    ),
                    in: 0...max(engine.duration, 0.001),
                    onEditingChanged: { editing in
                        if !editing, let value = scrub {
                            engine.seek(to: value)
                            position = value
                            scrub = nil
                        }
                        showChrome()
                    }
                )
                Text(Self.timecode(engine.duration))
                    .font(.caption.monospacedDigit())
            }

            HStack(spacing: 28) {
                controlButton("gobackward", label: "Restart") { engine.restart() }
                controlButton("gobackward.10", label: "Back 10 seconds") { engine.seekBy(-10) }
                Button {
                    engine.togglePlay()
                    showChrome()
                } label: {
                    Image(systemName: engine.isPlaying ? "pause.circle.fill" : "play.circle.fill")
                        .font(.system(size: 62))
                }
                controlButton("goforward.10", label: "Forward 10 seconds") { engine.seekBy(10) }
                controlButton("forward.end.fill", label: "Next in queue") { session.advance() }
                    .disabled(session.queue.isEmpty)
            }

            HStack(spacing: 16) {
                if engine.canToggle {
                    Picker("Track", selection: Binding(
                        get: { engine.track },
                        set: { engine.setTrack($0); showChrome() }
                    )) {
                        Text("Original").tag(AudioTrack.original)
                        Text("Karaoke").tag(AudioTrack.instrumental)
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 240)
                }
                if session.subtitle != nil {
                    HStack(spacing: 8) {
                        Button {
                            session.nudgeOffset(-100)
                            showChrome()
                        } label: {
                            Image(systemName: "minus")
                        }
                        Text("Lyrics \(session.offsetMs > 0 ? "+" : "")\(String(format: "%.1f", Double(session.offsetMs) / 1000))s")
                            .font(.caption.monospacedDigit())
                            .frame(width: 110)
                        Button {
                            session.nudgeOffset(100)
                            showChrome()
                        } label: {
                            Image(systemName: "plus")
                        }
                    }
                    .buttonStyle(.bordered)
                }
            }
        }
        .padding(.horizontal, 32)
        .padding(.bottom, 24)
        .foregroundStyle(.white)
        .tint(.white)
    }

    private func controlButton(_ symbol: String, label: String, action: @escaping () -> Void) -> some View {
        Button {
            action()
            showChrome()
        } label: {
            Image(systemName: symbol).font(.title)
        }
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
