import SwiftUI

/// The song library, laid out like the desktop player: a centred column with a
/// header, a search field, an optional singer chip, and a table of rows —
/// rather than the cover grid this started as.
struct LibraryView: View {
    @Environment(AppConfig.self) private var config
    @Environment(PlayerSession.self) private var session

    @State private var songs: [Song] = []
    @State private var search = ""
    @State private var artistFilter: String?
    @State private var loading = true
    @State private var error: String?
    @State private var showQueue = false
    @State private var showSettings = false
    @State private var searchTask: Task<Void, Never>?

    var body: some View {
        @Bindable var session = session
        ZStack(alignment: .top) {
            Theme.bg.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 16) {
                header
                if let artist = artistFilter { filterChip(artist) }
                content
            }
            .padding(.horizontal, 32)
            .padding(.top, 24)
            .frame(maxWidth: Theme.contentMaxWidth, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .preferredColorScheme(.dark)
        .safeAreaInset(edge: .bottom) {
            if session.current != nil && !session.isPresentingPlayer {
                MiniPlayerBar()
            }
        }
        .sheet(isPresented: $showQueue) { QueueSheet() }
        .sheet(isPresented: $showSettings) { SettingsSheet() }
        .fullScreenCover(isPresented: $session.isPresentingPlayer) { PlayerView() }
        .task { await reload() }
        .onChange(of: search) { _, _ in scheduleReload() }
        .onChange(of: artistFilter) { _, _ in Task { await reload() } }
    }

    // ---- header ------------------------------------------------------------

    private var header: some View {
        HStack(spacing: 16) {
            Text(artistFilter ?? "Karaoke")
                .font(.system(size: 22, weight: .bold))
                .foregroundStyle(Theme.text)
            Spacer(minLength: 0)
            searchField
            // Queues the list exactly as shown — same order, filters and all —
            // so "play all" after a singer filter means that singer's set.
            toolbarButton("play.fill", label: "Play all") {
                session.enqueue(contentsOf: playableSongs)
            }
            .disabled(playableSongs.isEmpty)
            .opacity(playableSongs.isEmpty ? 0.45 : 1)
            toolbarButton(
                "list.bullet",
                label: session.queue.isEmpty ? "Queue" : "Queue (\(session.queue.count))"
            ) { showQueue = true }
            toolbarButton("gearshape", label: nil) { showSettings = true }
        }
    }

    /// Songs the queue can actually take: a pending or failed import is still
    /// in the table, greyed out, and must not land in the list.
    private var playableSongs: [Song] { songs.filter(\.playable) }

    private var searchField: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 13))
                .foregroundStyle(Theme.textDim)
            TextField("Search songs and singers", text: $search)
                .textFieldStyle(.plain)
                .font(.system(size: 14))
                .foregroundStyle(Theme.text)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            if !search.isEmpty {
                Button {
                    search = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(Theme.textDim)
                }
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .frame(width: 300)
        .background(Theme.bg)
        .clipShape(RoundedRectangle(cornerRadius: 6))
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.border, lineWidth: 1))
    }

    private func toolbarButton(_ symbol: String, label: String?, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: symbol).font(.system(size: 14))
                if let label { Text(label).font(.system(size: 13, weight: .semibold)) }
            }
            .foregroundStyle(Theme.text)
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .background(Theme.bgRaised)
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.border, lineWidth: 1))
        }
    }

    private func filterChip(_ artist: String) -> some View {
        HStack(spacing: 8) {
            Text("SINGER")
                .font(.system(size: 11, weight: .regular))
                .tracking(0.55)
                .foregroundStyle(Theme.textDim)
            Text(artist)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Theme.text)
            Button {
                artistFilter = nil
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Theme.textDim)
                    .padding(4)
            }
        }
        .padding(.leading, 12)
        .padding(.trailing, 6)
        .padding(.vertical, 4)
        .background(Theme.bgHover)
        .clipShape(Capsule())
        .overlay(Capsule().stroke(Theme.border, lineWidth: 1))
    }

    // ---- table -------------------------------------------------------------

    @ViewBuilder
    private var content: some View {
        if loading && songs.isEmpty {
            centred { ProgressView().tint(Theme.textDim) }
        } else if let error {
            centred {
                VStack(spacing: 12) {
                    Text("Can't reach the server")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(Theme.text)
                    Text(error)
                        .font(.system(size: 13))
                        .foregroundStyle(Theme.textDim)
                        .multilineTextAlignment(.center)
                    HStack(spacing: 10) {
                        Button("Try again") { Task { await reload() } }
                        Button("Change server") { showSettings = true }
                    }
                    .buttonStyle(DesktopButtonStyle())
                }
            }
        } else if songs.isEmpty {
            centred {
                Text(search.isEmpty ? "No songs yet." : "Nothing matches “\(search)”.")
                    .foregroundStyle(Theme.textDim)
            }
        } else {
            ScrollView {
                LazyVStack(spacing: 0) {
                    columnHeader
                    ForEach(songs) { song in
                        SongRow(
                            song: song,
                            play: { session.playNow(song) },
                            enqueue: { session.enqueue(song) },
                            filterArtist: { artistFilter = song.artist })
                        Divider().overlay(Theme.border)
                    }
                }
                .padding(.bottom, 64)
            }
            .scrollIndicators(.hidden)
            .refreshable { await reload() }
        }
    }

    private var columnHeader: some View {
        HStack(spacing: 10) {
            Text("SONG")
            Spacer(minLength: 0)
            Text("LENGTH").frame(width: 64, alignment: .trailing)
            Text("STATUS").frame(width: 96, alignment: .trailing)
            Color.clear.frame(width: 184, height: 1)   // actions column
        }
        .font(.system(size: 12, weight: .medium))
        .foregroundStyle(Theme.textDim)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .overlay(alignment: .bottom) { Divider().overlay(Theme.border) }
    }

    private func centred<C: View>(@ViewBuilder _ body: () -> C) -> some View {
        VStack { Spacer(); body(); Spacer() }.frame(maxWidth: .infinity)
    }

    // ---- data --------------------------------------------------------------

    /// Typing shouldn't fire a request per keystroke.
    private func scheduleReload() {
        searchTask?.cancel()
        searchTask = Task {
            try? await Task.sleep(for: .milliseconds(300))
            guard !Task.isCancelled else { return }
            await reload()
        }
    }

    private func reload() async {
        guard let api = config.client else { return }
        session.configure(api: api)
        loading = true
        defer { loading = false }
        do {
            songs = try await api.listSongs(query: search, artist: artistFilter)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// One row of the table: cover, title over singer, length, pipeline status.
struct SongRow: View {
    @Environment(AppConfig.self) private var config

    let song: Song
    let play: () -> Void
    let enqueue: () -> Void
    let filterArtist: () -> Void

    @State private var hovering = false

    var body: some View {
        HStack(spacing: 10) {
            cover
            VStack(alignment: .leading, spacing: 2) {
                Text(song.displayTitle)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Theme.text)
                    .lineLimit(1)
                // Plain text, not a button: the desktop can afford a clickable
                // singer because a mouse aims precisely, but on a touch row the
                // whole point of tapping is "sing this", and a filter trigger
                // sitting inside the tap target only fires by accident.
                // Filtering lives in the long-press menu instead.
                Text(song.displayArtist)
                    .font(.system(size: 12))
                    .foregroundStyle(Theme.textDim)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
            if song.hasVideo {
                Image(systemName: "film")
                    .font(.system(size: 11))
                    .foregroundStyle(Theme.textDim)
            }
            Text(Self.duration(song.durationSec))
                .font(.system(size: 13).monospacedDigit())
                .foregroundStyle(Theme.textDim)
                .frame(width: 64, alignment: .trailing)
            StatusBadge(status: song.status).frame(width: 96, alignment: .trailing)
            // An explicit target to sing this one, so starting a song is a
            // deliberate press rather than a tap anywhere on the row.
            HStack(spacing: 6) {
                rowButton("play.fill", "Play", accessibility: "Play \(song.displayTitle)", action: play)
                rowButton("text.append", "Queue", accessibility: "Queue \(song.displayTitle)", action: enqueue)
            }
            .frame(width: 184, alignment: .trailing)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 10)
        .background(hovering ? Theme.bgRaised : .clear)
        .contentShape(Rectangle())
        .opacity(song.playable ? 1 : 0.45)
        .onTapGesture { if song.playable { play() } }
        .contextMenu {
            Button("Play now", systemImage: "play.fill", action: play)
            Button("Add to queue", systemImage: "text.append", action: enqueue)
            if song.artist?.isEmpty == false {
                Button("Only this singer", systemImage: "person", action: filterArtist)
            }
        }
    }

    /// Icon and word together: an icon alone leaves "play now" and "add to the
    /// queue" looking like two shades of the same thing, and a bare glyph is a
    /// small target for a thumb.
    private func rowButton(
        _ symbol: String, _ label: String, accessibility: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 5) {
                Image(systemName: symbol).font(.system(size: 11))
                Text(label).font(.system(size: 13, weight: .medium))
            }
            .foregroundStyle(Theme.text)
            .padding(.horizontal, 12)
            .frame(height: 30)
            .background(Theme.bgRaised)
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.border, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(accessibility)
    }

    private var cover: some View {
        RoundedRectangle(cornerRadius: 6)
            .fill(Theme.bgHover)
            .frame(width: 40, height: 40)
            .overlay {
                if song.hasCover, let api = config.client {
                    AsyncImage(url: api.coverURL(song)) { image in
                        image.resizable().scaledToFill()
                    } placeholder: {
                        Text("♪").foregroundStyle(Theme.textDim)
                    }
                } else {
                    Text("♪").foregroundStyle(Theme.textDim)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 6))
    }

    private static func duration(_ seconds: Double?) -> String {
        guard let seconds, seconds.isFinite else { return "—" }
        let total = Int(seconds.rounded())
        return String(format: "%d:%02d", total / 60, total % 60)
    }
}

/// The desktop's plain button: raised panel, hairline border, 6pt radius.
struct DesktopButtonStyle: ButtonStyle {
    var prominent = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13))
            .foregroundStyle(Theme.text)
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(prominent ? Theme.accentStrong : Theme.bgRaised)
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .overlay(
                RoundedRectangle(cornerRadius: 6)
                    .stroke(prominent ? Theme.accentStrong : Theme.border, lineWidth: 1))
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}
