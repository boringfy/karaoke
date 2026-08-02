import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import '../api/models.dart';
import '../player/playback_engine.dart';

/// The current lyric line with a smooth per-token wipe. A Ticker repaints a
/// CustomPainter every frame from the engine's interpolated position, so React-
/// style per-line rebuilds never happen on the hot path. Only the current line
/// is shown; during instrumental rests nothing is drawn.
class LyricsView extends StatefulWidget {
  final PlaybackEngine engine;
  final SubtitleDoc subtitle;
  final int offsetMs;
  const LyricsView({
    super.key,
    required this.engine,
    required this.subtitle,
    required this.offsetMs,
  });

  @override
  State<LyricsView> createState() => _LyricsViewState();
}

class _LyricsViewState extends State<LyricsView>
    with SingleTickerProviderStateMixin {
  late final Ticker _ticker;
  final ValueNotifier<int> _repaint = ValueNotifier(0);

  @override
  void initState() {
    super.initState();
    _ticker = createTicker((_) => _repaint.value++)..start();
  }

  @override
  void dispose() {
    _ticker.dispose();
    _repaint.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      painter: _LyricsPainter(
        engine: widget.engine,
        subtitle: widget.subtitle,
        offsetMs: widget.offsetMs,
        repaint: _repaint,
      ),
      size: Size.infinite,
    );
  }
}

// Regex for CJK: hiragana, katakana, CJK ideographs. Tokens on both sides CJK
// butt together; latin words get a space between them.
final _cjk = RegExp(r'[぀-ヿ㐀-鿿豈-﫿ｦ-ﾟ]');
bool _spaceBefore(String prev, String next) {
  if (prev.isEmpty || next.isEmpty) return false;
  return !_cjk.hasMatch(prev[prev.length - 1]) && !_cjk.hasMatch(next[0]);
}

class _Measured {
  final String lineId;
  final double width; // canvas width this layout was built for
  final double fontSize;
  final List<TextPainter> base;
  final List<TextPainter> fill;
  final List<TextPainter?> ruby;
  final List<double> x; // left edge of each token
  final List<double> w; // width of each token
  final double totalWidth;
  _Measured(this.lineId, this.width, this.fontSize, this.base, this.fill,
      this.ruby, this.x, this.w, this.totalWidth);
}

class _LyricsPainter extends CustomPainter {
  final PlaybackEngine engine;
  final SubtitleDoc subtitle;
  final int offsetMs;
  _Measured? _cache;

  _LyricsPainter({
    required this.engine,
    required this.subtitle,
    required this.offsetMs,
    required Listenable repaint,
  }) : super(repaint: repaint);

  static const _shadows = [
    Shadow(color: Colors.black, blurRadius: 5),
    Shadow(color: Colors.black, blurRadius: 3, offset: Offset(0, 2)),
  ];

  @override
  void paint(Canvas canvas, Size size) {
    final t = engine.positionSec - offsetMs / 1000.0;
    final idx = subtitle.lineIndexAt(t);
    if (idx < 0) return; // rest — draw nothing
    final line = subtitle.lines[idx];

    final m = _measure(line, size.width);
    final startX = ((size.width - m.totalWidth) / 2).clamp(8.0, size.width).toDouble();
    final baseY = size.height * 0.5;

    // Sweep boundary: fully-sung tokens filled, current token partially.
    double fillX = startX;
    for (var i = 0; i < line.tokens.length; i++) {
      final tok = line.tokens[i];
      final left = startX + m.x[i];
      if (t >= tok.end) {
        fillX = left + m.w[i];
      } else if (t >= tok.start) {
        fillX = left + tok.fill(t) * m.w[i];
        break;
      } else {
        break;
      }
    }

    // Ruby (furigana) above kanji.
    for (var i = 0; i < m.ruby.length; i++) {
      final rp = m.ruby[i];
      if (rp == null) continue;
      final cx = startX + m.x[i] + m.w[i] / 2;
      rp.paint(canvas, Offset(cx - rp.width / 2, baseY - m.fontSize * 0.62 - rp.height));
    }

    // Base (white) layer.
    for (var i = 0; i < m.base.length; i++) {
      m.base[i].paint(canvas, Offset(startX + m.x[i], baseY - m.base[i].height / 2));
    }
    // Highlight layer, clipped to the sweep boundary.
    canvas.save();
    canvas.clipRect(Rect.fromLTWH(0, 0, fillX, size.height));
    for (var i = 0; i < m.fill.length; i++) {
      m.fill[i].paint(canvas, Offset(startX + m.x[i], baseY - m.fill[i].height / 2));
    }
    canvas.restore();

    // Translation, if any, below the line.
    final tr = line.translation;
    if (tr != null && tr.isNotEmpty) {
      final tp = TextPainter(
        text: TextSpan(
          text: tr,
          style: TextStyle(
            color: Colors.white.withOpacity(0.85),
            fontSize: m.fontSize * 0.42,
            shadows: _shadows,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout(maxWidth: size.width * 0.9);
      tp.paint(canvas, Offset((size.width - tp.width) / 2, baseY + m.fontSize * 0.7));
    }
  }

  _Measured _measure(SubtitleLine line, double width) {
    if (_cache != null && _cache!.lineId == line.id && _cache!.width == width) {
      return _cache!;
    }
    var fontSize = (width * 0.055).clamp(26.0, 76.0).toDouble();

    _Measured build(double fs) {
      final base = <TextPainter>[];
      final fill = <TextPainter>[];
      final ruby = <TextPainter?>[];
      final xs = <double>[];
      final ws = <double>[];
      double cursor = 0;
      final spaceW = _tp(' ', fs, Colors.white).width;
      for (var i = 0; i < line.tokens.length; i++) {
        final tok = line.tokens[i];
        if (i > 0 && _spaceBefore(line.tokens[i - 1].text, tok.text)) {
          cursor += spaceW;
        }
        final b = _tp(tok.text, fs, Colors.white);
        final f = _tp(tok.text, fs, const Color(0xFFFFD54A));
        base.add(b);
        fill.add(f);
        ruby.add(tok.ruby == null || tok.ruby!.isEmpty
            ? null
            : _tp(tok.ruby!, fs * 0.42, Colors.white));
        xs.add(cursor);
        ws.add(b.width);
        cursor += b.width;
      }
      return _Measured(line.id, width, fs, base, fill, ruby, xs, ws, cursor);
    }

    var m = build(fontSize);
    // Shrink to fit the available width (with margins) if the line is long.
    final maxW = width * 0.94;
    if (m.totalWidth > maxW && m.totalWidth > 0) {
      fontSize = (fontSize * maxW / m.totalWidth).clamp(16.0, 76.0).toDouble();
      m = build(fontSize);
    }
    _cache = m;
    return m;
  }

  TextPainter _tp(String text, double fontSize, Color color) => TextPainter(
        text: TextSpan(
          text: text,
          style: TextStyle(
            color: color,
            fontSize: fontSize,
            fontWeight: FontWeight.w800,
            height: 1.1,
            shadows: _shadows,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();

  @override
  bool shouldRepaint(covariant _LyricsPainter old) => true; // driven by Ticker
}
