import SwiftUI

/// Leaving the player keeps the song going; this bar sits under the library so
/// the next singer can queue up without stopping the current one.
struct MiniPlayerBar: View {
    @Environment(PlayerSession.self) private var session

    var body: some View {
        HStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 2) {
                Text(session.current?.displayTitle ?? "")
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(1)
                // Live lyrics, at a rate that costs nothing next to the
                // per-frame wipe in the full player.
                TimelineView(.periodic(from: .now, by: 0.1)) { _ in
                    Text(currentLine ?? session.current?.displayArtist ?? "")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 0)
            Button {
                session.engine.togglePlay()
            } label: {
                Image(systemName: session.engine.isPlaying ? "pause.fill" : "play.fill")
                    .font(.title3)
            }
            Button {
                session.advance()
            } label: {
                Image(systemName: "forward.end.fill")
            }
            .disabled(session.queue.isEmpty)
            Button {
                session.stop()
            } label: {
                Image(systemName: "stop.fill")
            }
            Button {
                session.isPresentingPlayer = true
            } label: {
                Image(systemName: "chevron.up.circle.fill")
                    .font(.title2)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
        .background(.bar)
        .overlay(alignment: .top) { Divider() }
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
                    Section("Now singing") {
                        SongRow(song: current)
                    }
                }
                Section("Up next") {
                    if session.queue.isEmpty {
                        Text("Nothing queued — long-press a song to add it.")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(session.queue) { song in
                        SongRow(song: song)
                    }
                    .onDelete { session.remove(at: $0) }
                    .onMove { session.move(from: $0, to: $1) }
                }
            }
            .navigationTitle("Queue")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { EditButton() }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private struct SongRow: View {
        let song: Song
        var body: some View {
            VStack(alignment: .leading, spacing: 2) {
                Text(song.displayTitle).font(.body)
                Text(song.displayArtist).font(.caption).foregroundStyle(.secondary)
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
                        .font(.body.monospaced())
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    if let reachable {
                        Label(
                            reachable ? "Server is reachable" : "No answer from that address",
                            systemImage: reachable ? "checkmark.circle.fill" : "xmark.circle.fill"
                        )
                        .foregroundStyle(reachable ? .green : .red)
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
            .navigationTitle("Server")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                }
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
    }
}
