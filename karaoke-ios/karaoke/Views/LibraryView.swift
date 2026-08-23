import SwiftUI

/// The song library: a cover-art grid sized for an iPad, with search, a
/// singer filter, the sing-along queue, and a mini-player for whatever is
/// already on stage.
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

    private let columns = [GridItem(.adaptive(minimum: 190, maximum: 260), spacing: 20)]

    var body: some View {
        @Bindable var session = session
        NavigationStack {
            content
                .navigationTitle(artistFilter ?? "Karaoke")
                .navigationBarTitleDisplayMode(.large)
                .searchable(text: $search, prompt: "Search songs and singers")
                .toolbar { toolbar }
                .safeAreaInset(edge: .bottom) {
                    if session.current != nil && !session.isPresentingPlayer {
                        MiniPlayerBar()
                    }
                }
        }
        .sheet(isPresented: $showQueue) { QueueSheet() }
        .sheet(isPresented: $showSettings) { SettingsSheet() }
        .fullScreenCover(isPresented: $session.isPresentingPlayer) { PlayerView() }
        .task { await reload() }
        .onChange(of: search) { _, _ in scheduleReload() }
        .onChange(of: artistFilter) { _, _ in Task { await reload() } }
        .refreshable { await reload() }
    }

    @ViewBuilder
    private var content: some View {
        if loading && songs.isEmpty {
            ProgressView("Loading library…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let error {
            ContentUnavailableView {
                Label("Can't reach the server", systemImage: "wifi.exclamationmark")
            } description: {
                Text(error)
            } actions: {
                Button("Try again") { Task { await reload() } }
                Button("Change server") { showSettings = true }
            }
        } else if songs.isEmpty {
            ContentUnavailableView.search
        } else {
            ScrollView {
                if let artistFilter {
                    HStack {
                        Button {
                            self.artistFilter = nil
                        } label: {
                            Label(artistFilter, systemImage: "xmark.circle.fill")
                        }
                        .buttonStyle(.bordered)
                        .clipShape(Capsule())
                        Spacer()
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 8)
                }
                LazyVGrid(columns: columns, spacing: 22) {
                    ForEach(songs) { song in
                        SongCard(song: song) {
                            session.playNow(song)
                        } enqueue: {
                            session.enqueue(song)
                        } filterArtist: {
                            artistFilter = song.artist
                        }
                    }
                }
                .padding(20)
            }
        }
    }

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .topBarTrailing) {
            Button {
                showQueue = true
            } label: {
                // The count is spelled out: a toolbar badge is unreliable here,
                // and how many singers are waiting is the whole point.
                Label(
                    session.queue.isEmpty ? "Queue" : "Queue (\(session.queue.count))",
                    systemImage: "list.bullet")
            }
        }
        ToolbarItem(placement: .topBarTrailing) {
            Button {
                showSettings = true
            } label: {
                Label("Server", systemImage: "gearshape")
            }
        }
    }

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

/// One song in the grid: cover art, title, singer, and a state badge for
/// anything the server hasn't finished processing.
struct SongCard: View {
    @Environment(AppConfig.self) private var config

    let song: Song
    let play: () -> Void
    let enqueue: () -> Void
    let filterArtist: () -> Void

    var body: some View {
        Button(action: play) {
            VStack(alignment: .leading, spacing: 8) {
                // The square tile decides its own size and the artwork is laid
                // over it: art in a ZStack sizes the stack instead, so a cover
                // wider than the cell spills across its neighbours.
                RoundedRectangle(cornerRadius: 12)
                    .fill(.quaternary)
                    .aspectRatio(1, contentMode: .fit)
                    .overlay {
                        if song.hasCover, let api = config.client {
                            AsyncImage(url: api.coverURL(song)) { image in
                                image.resizable().scaledToFill()
                            } placeholder: {
                                Image(systemName: "music.note")
                                    .font(.system(size: 34))
                                    .foregroundStyle(.secondary)
                            }
                        } else {
                            Image(systemName: song.hasVideo ? "film" : "music.note")
                                .font(.system(size: 34))
                                .foregroundStyle(.secondary)
                        }
                    }
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                    .overlay(alignment: .topTrailing) { badge }

                Text(song.displayTitle)
                    .font(.headline)
                    .lineLimit(1)
                Text(song.displayArtist)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .buttonStyle(.plain)
        .opacity(song.playable ? 1 : 0.45)
        .disabled(!song.playable)
        .contextMenu {
            Button("Play now", systemImage: "play.fill", action: play)
            Button("Add to queue", systemImage: "text.append", action: enqueue)
            if song.artist?.isEmpty == false {
                Button("Only this singer", systemImage: "person", action: filterArtist)
            }
        }
    }

    @ViewBuilder
    private var badge: some View {
        if !song.playable {
            Text(song.status.replacingOccurrences(of: "_", with: " "))
                .font(.caption2.weight(.semibold))
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(.thinMaterial, in: Capsule())
                .padding(8)
        } else if song.hasVideo {
            Image(systemName: "film.fill")
                .font(.caption)
                .padding(6)
                .background(.thinMaterial, in: Circle())
                .padding(8)
        }
    }
}
