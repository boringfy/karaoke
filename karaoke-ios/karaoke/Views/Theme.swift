import SwiftUI

/// The desktop player's palette, so the two clients read as one product.
/// Mirrors the custom properties in karaoke-player/src/styles/global.css.
enum Theme {
    static let bg = Color(hex: 0x0F1115)
    static let bgRaised = Color(hex: 0x171A21)
    static let bgHover = Color(hex: 0x1F232D)
    static let border = Color(hex: 0x2A2F3A)
    static let text = Color(hex: 0xE8EAF0)
    static let textDim = Color(hex: 0x9AA1AF)
    static let accent = Color(hex: 0x6C8CFF)
    static let accentStrong = Color(hex: 0x4A6EF5)
    static let danger = Color(hex: 0xE5586A)
    static let ok = Color(hex: 0x46C07A)
    static let warn = Color(hex: 0xE0A84C)
    static let highlight = Color(hex: 0xFFD54A)

    /// The desktop centres its library in a fixed column rather than letting
    /// rows run the full width of a wide display; an iPad is wide enough to
    /// want the same restraint.
    static let contentMaxWidth: CGFloat = 1100
}

extension Color {
    init(hex: UInt32) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: 1)
    }
}

/// The desktop's pipeline-status pill: the status colour at 15% behind the
/// same colour as text. One per song, whatever the status.
struct StatusBadge: View {
    let status: String

    private var label: String {
        switch status {
        case "pending": "Pending"
        case "processing": "Processing"
        case "ready": "Ready"
        case "needs_review": "Needs review"
        case "failed": "Failed"
        default: status
        }
    }

    private var color: Color {
        switch status {
        case "ready": Theme.ok
        case "pending", "processing": Theme.accent
        case "needs_review": Theme.warn
        case "failed": Theme.danger
        default: Theme.textDim
        }
    }

    var body: some View {
        Text(label)
            .font(.system(size: 11, weight: .semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 9)
            .padding(.vertical, 2)
            .background(color.opacity(0.15), in: RoundedRectangle(cornerRadius: 10))
    }
}
