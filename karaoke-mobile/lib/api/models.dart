// Dart mirrors of the karaoke-server JSON schemas.

class Song {
  final String id;
  final String? title;
  final String? artist;
  final String? album;
  final String language; // en | zh | ja | unknown
  final double? durationSec;
  final String status; // pending | processing | needs_review | ready | failed
  final double? alignmentConfidence;
  final String? instrumentalSource; // uploaded | generated | null
  final int subtitleOffsetMs;
  final bool hasOriginal;
  final bool hasInstrumental;
  final bool hasVideo;
  final bool hasCover;
  final bool hasSubtitle;
  final String updatedAt;

  Song({
    required this.id,
    this.title,
    this.artist,
    this.album,
    required this.language,
    this.durationSec,
    required this.status,
    this.alignmentConfidence,
    this.instrumentalSource,
    this.subtitleOffsetMs = 0,
    this.hasOriginal = false,
    this.hasInstrumental = false,
    this.hasVideo = false,
    this.hasCover = false,
    this.hasSubtitle = false,
    this.updatedAt = '',
  });

  bool get playable => status == 'ready' || status == 'needs_review';

  factory Song.fromJson(Map<String, dynamic> j) => Song(
        id: j['id'] as String,
        title: j['title'] as String?,
        artist: j['artist'] as String?,
        album: j['album'] as String?,
        language: (j['language'] ?? 'unknown') as String,
        durationSec: (j['duration_sec'] as num?)?.toDouble(),
        status: j['status'] as String,
        alignmentConfidence: (j['alignment_confidence'] as num?)?.toDouble(),
        instrumentalSource: j['instrumental_source'] as String?,
        subtitleOffsetMs: (j['subtitle_offset_ms'] as num?)?.toInt() ?? 0,
        hasOriginal: j['has_original'] == true,
        hasInstrumental: j['has_instrumental'] == true,
        hasVideo: j['has_video'] == true,
        hasCover: j['has_cover'] == true,
        hasSubtitle: j['has_subtitle'] == true,
        updatedAt: (j['updated_at'] ?? '') as String,
      );
}

class SubtitleToken {
  final String text;
  final double start;
  final double end;
  final String? ruby; // furigana (ja)
  SubtitleToken(this.text, this.start, this.end, this.ruby);

  factory SubtitleToken.fromJson(Map<String, dynamic> j) => SubtitleToken(
        (j['text'] ?? '') as String,
        (j['start'] as num).toDouble(),
        (j['end'] as num).toDouble(),
        j['ruby'] as String?,
      );

  /// Fill fraction [0,1] at lyric-time [t] (seconds).
  double fill(double t) {
    if (t <= start) return 0;
    if (t >= end) return 1;
    final span = end - start;
    return span > 0 ? (t - start) / span : 1;
  }
}

class SubtitleLine {
  final String id;
  final double start;
  final double end;
  final String text;
  final String? translation;
  final List<SubtitleToken> tokens;
  SubtitleLine(this.id, this.start, this.end, this.text, this.translation, this.tokens);

  factory SubtitleLine.fromJson(Map<String, dynamic> j) => SubtitleLine(
        j['id'].toString(),
        (j['start'] as num).toDouble(),
        (j['end'] as num).toDouble(),
        (j['text'] ?? '') as String,
        j['translation'] as String?,
        ((j['tokens'] ?? []) as List)
            .map((t) => SubtitleToken.fromJson(t as Map<String, dynamic>))
            .toList(),
      );
}

class SubtitleDoc {
  final String lang;
  final int offsetMs;
  final List<SubtitleLine> lines;
  SubtitleDoc(this.lang, this.offsetMs, this.lines);

  factory SubtitleDoc.fromJson(Map<String, dynamic> j) => SubtitleDoc(
        (j['lang'] ?? 'unknown') as String,
        (j['offset_ms'] as num?)?.toInt() ?? 0,
        ((j['lines'] ?? []) as List)
            .map((l) => SubtitleLine.fromJson(l as Map<String, dynamic>))
            .toList(),
      );

  /// Index of the line covering lyric-time [t], or -1 in a gap/rest.
  int lineIndexAt(double t) {
    var lo = 0, hi = lines.length - 1, cand = -1;
    while (lo <= hi) {
      final mid = (lo + hi) >> 1;
      if (lines[mid].start <= t) {
        cand = mid;
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    if (cand >= 0 && t <= lines[cand].end) return cand;
    return -1;
  }
}
