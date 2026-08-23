import Foundation
import Observation

/// Holds the LAN address of karaoke-server, persisted across launches
/// (e.g. http://192.168.1.50:8787).
@Observable
final class AppConfig {
    private static let key = "server_base"

    private(set) var serverBase: String

    init() {
        serverBase = UserDefaults.standard.string(forKey: Self.key) ?? ""
    }

    var isConfigured: Bool { !serverBase.isEmpty }

    var client: APIClient? {
        guard let url = URL(string: serverBase) else { return nil }
        return APIClient(base: url)
    }

    /// Accepts what a person would actually type — `192.168.1.50`,
    /// `192.168.1.50:8787`, or a full URL — and normalises it.
    static func normalize(_ raw: String) -> String? {
        var v = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !v.isEmpty else { return nil }
        if !v.hasPrefix("http://") && !v.hasPrefix("https://") { v = "http://" + v }
        while v.hasSuffix("/") { v.removeLast() }
        guard var comps = URLComponents(string: v), comps.host?.isEmpty == false else { return nil }
        if comps.port == nil { comps.port = 8787 }
        return comps.url?.absoluteString
    }

    func setServerBase(_ raw: String) {
        guard let normalized = Self.normalize(raw) else { return }
        serverBase = normalized
        UserDefaults.standard.set(normalized, forKey: Self.key)
    }

    func clear() {
        serverBase = ""
        UserDefaults.standard.removeObject(forKey: Self.key)
    }
}
