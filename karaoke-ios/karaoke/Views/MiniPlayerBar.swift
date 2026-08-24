import SwiftUI

/// The desktop's floating mini-player: a 60pt bar over the library showing the
/// live lyric line, with transport on the right. Leaving the player keeps the
/// song going, so the next singer can queue up.
struct MiniPlayerBar: View {
    @Environment(PlayerSession.self) private var session

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 1) {
                Text(session.current?.displayTitle ?? "")
                    .font(.system(size: 11))
                    .foregroundStyle(Theme.textDim)
                    .lineLimit(1)
                // Live lyrics, at a rate that costs nothing next to the
                // per-frame wipe in the full player.
                TimelineView(.periodic(from: .now, by: 0.1)) { _ in
                    Text(currentLine ?? session.current?.displayArtist ?? "")
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(Theme.text)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 8)
            control(session.engine.isPlaying ? "pause.fill" : "play.fill") {
                session.engine.togglePlay()
            }
            control("forward.end.fill") { session.advance() }
                .disabled(session.queue.isEmpty)
                .opacity(session.queue.isEmpty ? 0.45 : 1)
            control("stop.fill") { session.stop() }
            control("chevron.up") { session.isPresentingPlayer = true }
        }
        .padding(.horizontal, 12)
        .frame(height: 60)
        .frame(maxWidth: 920)
        .background(Theme.bgRaised.opacity(0.96))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Theme.border, lineWidth: 1))
        .shadow(color: .black.opacity(0.5), radius: 15, y: 8)
        .padding(.horizontal, 16)
        .padding(.bottom, 16)
        .contentShape(Rectangle())
        .onTapGesture { session.isPresentingPlayer = true }
    }

    private func control(_ symbol: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 14))
                .foregroundStyle(Theme.text)
                .frame(width: 34, height: 30)
                .background(Color.white.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 6))
        }
        .buttonStyle(.plain)
    }

    private var currentLine: String? {
        guard let subtitle = session.subtitle else { return nil }
        let t = session.engine.positionSec - Double(session.offsetMs) / 1000
        guard let index = subtitle.lineIndex(at: t) else { return nil }
        return subtitle.lines[index].text
    }
}

/// The sing-along queue: reorder it, drop songs from it, or jump ahead.
struct QueueSheet: View {
    @Environment(PlayerSession.self) private var session
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                if let current = session.current {
                    Section("Now singing") { SongRowCompact(song: current) }
                }
                Section("Up next") {
                    if session.queue.isEmpty {
                        Text("Nothing queued — long-press a song to add it.")
                            .foregroundStyle(Theme.textDim)
                    }
                    ForEach(session.queue) { song in SongRowCompact(song: song) }
                        .onDelete { session.remove(at: $0) }
                        .onMove { session.move(from: $0, to: $1) }
                }
            }
            .scrollContentBackground(.hidden)
            .background(Theme.bg)
            .navigationTitle("Queue")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { EditButton() }
                ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } }
            }
        }
        .preferredColorScheme(.dark)
    }

    private struct SongRowCompact: View {
        let song: Song
        var body: some View {
            VStack(alignment: .leading, spacing: 2) {
                Text(song.displayTitle).font(.system(size: 14, weight: .semibold))
                Text(song.displayArtist).font(.system(size: 12)).foregroundStyle(Theme.textDim)
            }
        }
    }
}

/// Which karaoke-server this iPad is pointed at.
struct SettingsSheet: View {
    @Environment(AppConfig.self) private var config
    @Environment(\.dismiss) private var dismiss

    @State private var address = ""
    @State private var reachable: Bool?

    var body: some View {
        NavigationStack {
            Form {
                Section("Server address") {
                    TextField("192.168.1.50:8787", text: $address)
                        .font(.system(size: 14).monospaced())
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    if let reachable {
                        Label(
                            reachable ? "Server is reachable" : "No answer from that address",
                            systemImage: reachable ? "checkmark.circle.fill" : "xmark.circle.fill"
                        )
                        .foregroundStyle(reachable ? Theme.ok : Theme.danger)
                    }
                    Button("Test connection") {
                        Task {
                            guard let normalized = AppConfig.normalize(address),
                                  let url = URL(string: normalized) else {
                                reachable = false
                                return
                            }
                            reachable = await APIClient(base: url).ping()
                        }
                    }
                }
                Section {
                    Button("Forget this server", role: .destructive) {
                        config.clear()
                        dismiss()
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .background(Theme.bg)
            .navigationTitle("Server")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Save") {
                        config.setServerBase(address)
                        dismiss()
                    }
                    .disabled(AppConfig.normalize(address) == nil)
                }
            }
            .onAppear { address = config.serverBase }
        }
        .preferredColorScheme(.dark)
    }
}
