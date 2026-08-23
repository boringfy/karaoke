import Foundation

/// Thin REST client for karaoke-server. Media (audio/video/cover) are exposed
/// as URLs handed straight to AVPlayer / AsyncImage — the server serves them
/// with HTTP range support, so seeking works without downloading first.
struct APIClient: Sendable {
    let base: URL

    private var api: URL { base.appendingPathComponent("api/v1") }

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private static let session: URLSession = {
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 10
        cfg.waitsForConnectivity = false
        return URLSession(configuration: cfg)
    }()

    func ping() async -> Bool {
        var req = URLRequest(url: base.appendingPathComponent("health"))
        req.timeoutInterval = 5
        guard let (_, resp) = try? await Self.session.data(for: req),
              let http = resp as? HTTPURLResponse else { return false }
        return http.statusCode == 200
    }

    func listSongs(query: String = "", artist: String? = nil, limit: Int = 500) async throws -> [Song] {
        var comps = URLComponents(url: api.appendingPathComponent("songs"), resolvingAgainstBaseURL: false)!
        var items = [URLQueryItem(name: "limit", value: String(limit))]
        if !query.isEmpty { items.append(URLQueryItem(name: "q", value: query)) }
        if let artist, !artist.isEmpty { items.append(URLQueryItem(name: "artist", value: artist)) }
        comps.queryItems = items
        let (data, resp) = try await Self.session.data(from: comps.url!)
        try Self.check(resp)
        return try Self.decoder.decode(SongList.self, from: data).items
    }

    func song(_ id: String) async throws -> Song {
        let (data, resp) = try await Self.session.data(from: api.appendingPathComponent("songs/\(id)"))
        try Self.check(resp)
        return try Self.decoder.decode(Song.self, from: data)
    }

    /// Timed lyrics, or nil when the song genuinely has none (404).
    func subtitle(_ songId: String) async throws -> SubtitleDoc? {
        var comps = URLComponents(
            url: api.appendingPathComponent("songs/\(songId)/subtitle"),
            resolvingAgainstBaseURL: false)!
        comps.queryItems = [URLQueryItem(name: "format", value: "json")]
        let (data, resp) = try await Self.session.data(from: comps.url!)
        if let http = resp as? HTTPURLResponse, http.statusCode == 404 { return nil }
        try Self.check(resp)
        return try Self.decoder.decode(SubtitleDoc.self, from: data)
    }

    /// Persist the per-song lyric nudge so every client sees the same timing.
    func setSubtitleOffset(_ songId: String, offsetMs: Int) async throws {
        var req = URLRequest(url: api.appendingPathComponent("songs/\(songId)/subtitle/offset"))
        req.httpMethod = "PATCH"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["offset_ms": offsetMs])
        let (_, resp) = try await Self.session.data(for: req)
        try Self.check(resp)
    }

    // ---- media URLs --------------------------------------------------------

    func audioURL(_ songId: String, track: String) -> URL {
        var comps = URLComponents(
            url: api.appendingPathComponent("songs/\(songId)/audio"),
            resolvingAgainstBaseURL: false)!
        // This URL carries no file extension, so AVFoundation identifies the
        // container purely from the response's Content-Type; karaoke-server
        // labels audio correctly as of "Label served audio with its real
        // container type".
        //
        // Below iOS 26, AVFoundation cannot decode Ogg/Opus at all — measured
        // on iOS 18.1.1 — and most instrumentals this server generates are
        // Opus, so ask for an AAC rendition instead. iOS 26 plays Opus
        // natively and skips the request, sparing the server a transcode. A
        // server that does not implement `codec` ignores it and returns Opus,
        // which is exactly the state that cannot play. See
        // BACKEND_REQUIREMENTS.md, requirement 2.
        var items = [URLQueryItem(name: "track", value: track)]
        if #unavailable(iOS 26) {
            items.append(URLQueryItem(name: "codec", value: "aac"))
        }
        comps.queryItems = items
        return comps.url!
    }

    func videoURL(_ songId: String) -> URL {
        api.appendingPathComponent("songs/\(songId)/video")
    }

    /// `updatedAt` busts the image cache when the cover art is replaced.
    func coverURL(_ song: Song) -> URL {
        var comps = URLComponents(
            url: api.appendingPathComponent("songs/\(song.id)/cover"),
            resolvingAgainstBaseURL: false)!
        comps.queryItems = [URLQueryItem(name: "v", value: song.updatedAt)]
        return comps.url!
    }

    private static func check(_ resp: URLResponse) throws {
        guard let http = resp as? HTTPURLResponse else { return }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.http(http.statusCode)
        }
    }
}

enum APIError: LocalizedError {
    case http(Int)

    var errorDescription: String? {
        switch self {
        case .http(let code): "server returned HTTP \(code)"
        }
    }
}
