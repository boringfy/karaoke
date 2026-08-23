import Foundation

// Swift mirrors of the karaoke-server JSON schemas (karaoke_server/api/schemas.py
// and karaoke_server/subtitles/schema.py). Everything is decoded defensively:
// the server omits null fields, and an older server should not break the app.

struct Song: Identifiable, Codable, Hashable {
    let id: String
    var title: String?
    var artist: String?
    var album: String?
    var language: String
    var durationSec: Double?
    var status: String
    var subtitleOffsetMs: Int
    var videoOffsetMs: Int
    var embeddedLyrics: Bool
    var hasOriginal: Bool
    var hasInstrumental: Bool
    var hasVideo: Bool
    var hasCover: Bool
    var hasSubtitle: Bool
    var updatedAt: String

    /// Songs still in the pipeline can't be sung yet.
    var playable: Bool { status == "ready" || status == "needs_review" }
    var displayTitle: String { title?.isEmpty == false ? title! : "Untitled" }
    var displayArtist: String { artist?.isEmpty == false ? artist! : "Unknown artist" }

    enum CodingKeys: String, CodingKey {
        case id, title, artist, album, language, status
        case durationSec, subtitleOffsetMs, videoOffsetMs, embeddedLyrics
        case hasOriginal, hasInstrumental, hasVideo, hasCover, hasSubtitle
        case updatedAt
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decodeIfPresent(String.self, forKey: .title)
        artist = try c.decodeIfPresent(String.self, forKey: .artist)
        album = try c.decodeIfPresent(String.self, forKey: .album)
        language = try c.decodeIfPresent(String.self, forKey: .language) ?? "unknown"
        durationSec = try c.decodeIfPresent(Double.self, forKey: .durationSec)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "pending"
        subtitleOffsetMs = try c.decodeIfPresent(Int.self, forKey: .subtitleOffsetMs) ?? 0
        videoOffsetMs = try c.decodeIfPresent(Int.self, forKey: .videoOffsetMs) ?? 0
        embeddedLyrics = try c.decodeIfPresent(Bool.self, forKey: .embeddedLyrics) ?? false
        hasOriginal = try c.decodeIfPresent(Bool.self, forKey: .hasOriginal) ?? false
        hasInstrumental = try c.decodeIfPresent(Bool.self, forKey: .hasInstrumental) ?? false
        hasVideo = try c.decodeIfPresent(Bool.self, forKey: .hasVideo) ?? false
        hasCover = try c.decodeIfPresent(Bool.self, forKey: .hasCover) ?? false
        hasSubtitle = try c.decodeIfPresent(Bool.self, forKey: .hasSubtitle) ?? false
        updatedAt = try c.decodeIfPresent(String.self, forKey: .updatedAt) ?? ""
    }
}

struct SongList: Codable {
    var total: Int
    var items: [Song]
}

/// One highlightable unit: a word (EN) or a character (ZH/JA).
struct SubtitleToken: Codable, Hashable {
    var text: String
    var start: Double
    var end: Double
    /// Hiragana reading drawn above the token (Japanese kanji only).
    var ruby: String?

    /// Fill fraction in 0...1 at lyric-time `t` (seconds).
    func fill(at t: Double) -> Double {
        if t <= start { return 0 }
        if t >= end { return 1 }
        let span = end - start
        return span > 0 ? (t - start) / span : 1
    }

    enum CodingKeys: String, CodingKey { case text, start, end, ruby }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        start = try c.decodeIfPresent(Double.self, forKey: .start) ?? 0
        end = try c.decodeIfPresent(Double.self, forKey: .end) ?? 0
        ruby = try c.decodeIfPresent(String.self, forKey: .ruby)
    }
}

struct SubtitleLine: Codable, Hashable, Identifiable {
    var id: String
    var start: Double
    var end: Double
    var text: String
    var translation: String?
    var tokens: [SubtitleToken]

    enum CodingKeys: String, CodingKey { case id, start, end, text, translation, tokens }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        // `id` is a string in practice but tolerate a number.
        if let s = try? c.decode(String.self, forKey: .id) {
            id = s
        } else if let n = try? c.decode(Int.self, forKey: .id) {
            id = String(n)
        } else {
            id = UUID().uuidString
        }
        start = try c.decodeIfPresent(Double.self, forKey: .start) ?? 0
        end = try c.decodeIfPresent(Double.self, forKey: .end) ?? 0
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        translation = try c.decodeIfPresent(String.self, forKey: .translation)
        tokens = try c.decodeIfPresent([SubtitleToken].self, forKey: .tokens) ?? []
    }
}

struct SubtitleDoc: Codable {
    var lang: String
    var offsetMs: Int
    var lines: [SubtitleLine]

    enum CodingKeys: String, CodingKey { case lang, offsetMs, lines }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        lang = try c.decodeIfPresent(String.self, forKey: .lang) ?? "unknown"
        offsetMs = try c.decodeIfPresent(Int.self, forKey: .offsetMs) ?? 0
        lines = try c.decodeIfPresent([SubtitleLine].self, forKey: .lines) ?? []
    }

    /// How early an upcoming line may be shown (unfilled) before it is sung.
    static let previewLeadS: Double = 10

    /// Index of the line to DISPLAY at lyric-time `t`, or nil during a rest.
    /// A line is displayed from max(previous line's end, start - 10s) until its
    /// end: short gaps show the next line immediately, long breaks preview it
    /// 10 s ahead. The wipe still starts at the line's real start.
    func lineIndex(at t: Double) -> Int? {
        for i in lines.indices {
            if lines[i].end <= t { continue }
            let prevEnd = i > 0 ? lines[i - 1].end : -Double.infinity
            let displayFrom = max(prevEnd, lines[i].start - Self.previewLeadS)
            return t >= displayFrom ? i : nil
        }
        return nil
    }
}
