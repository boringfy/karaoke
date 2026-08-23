import SwiftUI

/// The current lyric line with a smooth per-token wipe. A `TimelineView(.animation)`
/// redraws a `Canvas` every frame straight from the engine clock, so the fill
/// never quantises to a UI tick — per word (EN) or per character (ZH/JA), with
/// furigana above kanji and a dark halo so it stays readable over any MV.
struct LyricsCanvas: View {
    let engine: PlaybackEngine
    let subtitle: SubtitleDoc
    let offsetMs: Int

    @State private var cache = LyricsLayoutCache()

    private static let fillColor = Color(red: 1, green: 0.835, blue: 0.29)

    var body: some View {
        TimelineView(.animation) { _ in
            Canvas { context, size in
                draw(&context, size)
            }
        }
        .allowsHitTesting(false)
    }

    private func draw(_ ctx: inout GraphicsContext, _ size: CGSize) {
        let t = engine.positionSec - Double(offsetMs) / 1000
        guard let index = subtitle.lineIndex(at: t) else { return } // rest: draw nothing
        let line = subtitle.lines[index]
        guard !line.tokens.isEmpty else { return }

        let layout = cache.layout(for: line, width: size.width, in: ctx)
        let startX = max(8, (size.width - layout.totalWidth) / 2)
        let baseY = size.height * 0.5

        // Sweep boundary: finished tokens fully filled, the current one partly.
        var fillX = startX
        for (i, token) in line.tokens.enumerated() {
            let left = startX + layout.x[i]
            if t >= token.end {
                fillX = left + layout.width[i]
            } else if t >= token.start {
                fillX = left + token.fill(at: t) * layout.width[i]
                break
            } else {
                break
            }
        }

        let shadow = GraphicsContext.Filter.shadow(color: .black.opacity(0.85), radius: 6, x: 0, y: 2)

        // Furigana above the kanji it reads.
        ctx.drawLayer { layer in
            layer.addFilter(shadow)
            for (i, token) in line.tokens.enumerated() {
                guard let ruby = token.ruby, !ruby.isEmpty else { continue }
                let cx = startX + layout.x[i] + layout.width[i] / 2
                layer.draw(
                    Text(ruby).font(.system(size: layout.fontSize * 0.42, weight: .semibold))
                        .foregroundStyle(.white),
                    at: CGPoint(x: cx, y: baseY - layout.fontSize * 0.62), anchor: .bottom)
            }
        }

        // Unsung base layer, then the highlight clipped to the sweep boundary.
        ctx.drawLayer { layer in
            layer.addFilter(shadow)
            drawTokens(line, layout, startX: startX, baseY: baseY, color: .white, into: &layer)
        }
        ctx.drawLayer { layer in
            layer.clip(to: Path(CGRect(x: 0, y: 0, width: fillX, height: size.height)))
            layer.addFilter(shadow)
            drawTokens(line, layout, startX: startX, baseY: baseY, color: Self.fillColor, into: &layer)
        }

        if let translation = line.translation, !translation.isEmpty {
            ctx.drawLayer { layer in
                layer.addFilter(shadow)
                layer.draw(
                    Text(translation).font(.system(size: layout.fontSize * 0.42))
                        .foregroundStyle(.white.opacity(0.85)),
                    at: CGPoint(x: size.width / 2, y: baseY + layout.fontSize * 0.7), anchor: .top)
            }
        }
    }

    private func drawTokens(
        _ line: SubtitleLine, _ layout: LyricsLayout,
        startX: CGFloat, baseY: CGFloat, color: Color, into ctx: inout GraphicsContext
    ) {
        for (i, token) in line.tokens.enumerated() {
            ctx.draw(
                Text(token.text).font(.system(size: layout.fontSize, weight: .heavy))
                    .foregroundStyle(color),
                at: CGPoint(x: startX + layout.x[i], y: baseY), anchor: .leading)
        }
    }
}

struct LyricsLayout {
    var fontSize: CGFloat
    var x: [CGFloat]
    var width: [CGFloat]
    var totalWidth: CGFloat
}

/// Measuring every token costs real time, and the line only changes a few times
/// a minute — so measure once per (line, width) and reuse it for every frame.
@MainActor
final class LyricsLayoutCache {
    private var lineID: String?
    private var canvasWidth: CGFloat = 0
    private var cached: LyricsLayout?

    func layout(for line: SubtitleLine, width: CGFloat, in ctx: GraphicsContext) -> LyricsLayout {
        if let cached, lineID == line.id, canvasWidth == width { return cached }
        var fontSize = min(max(width * 0.055, 26), 76)
        var layout = measure(line, fontSize: fontSize, in: ctx)
        // Long lines shrink to fit rather than running off the screen edge.
        let maxWidth = width * 0.94
        if layout.totalWidth > maxWidth && layout.totalWidth > 0 {
            fontSize = min(max(fontSize * maxWidth / layout.totalWidth, 16), 76)
            layout = measure(line, fontSize: fontSize, in: ctx)
        }
        lineID = line.id
        canvasWidth = width
        cached = layout
        return layout
    }

    private func measure(_ line: SubtitleLine, fontSize: CGFloat, in ctx: GraphicsContext) -> LyricsLayout {
        let proposal = CGSize(width: 10_000, height: 10_000)
        func widthOf(_ s: String) -> CGFloat {
            ctx.resolve(Text(s).font(.system(size: fontSize, weight: .heavy))).measure(in: proposal).width
        }
        let spaceWidth = widthOf(" ")
        var xs: [CGFloat] = []
        var ws: [CGFloat] = []
        var cursor: CGFloat = 0
        for (i, token) in line.tokens.enumerated() {
            if i > 0, Self.needsSpace(between: line.tokens[i - 1].text, and: token.text) {
                cursor += spaceWidth
            }
            let w = widthOf(token.text)
            xs.append(cursor)
            ws.append(w)
            cursor += w
        }
        return LyricsLayout(fontSize: fontSize, x: xs, width: ws, totalWidth: cursor)
    }

    /// CJK tokens butt together; latin words need a space between them.
    nonisolated static func needsSpace(between prev: String, and next: String) -> Bool {
        guard let last = prev.unicodeScalars.last, let first = next.unicodeScalars.first else { return false }
        return !isCJK(last) && !isCJK(first)
    }

    nonisolated static func isCJK(_ scalar: Unicode.Scalar) -> Bool {
        switch scalar.value {
        case 0x3040...0x30FF,   // hiragana + katakana
             0x3400...0x4DBF,   // CJK ext A
             0x4E00...0x9FFF,   // CJK unified
             0xF900...0xFAFF,   // compatibility ideographs
             0xFF66...0xFF9F:   // halfwidth katakana
            return true
        default:
            return false
        }
    }
}
