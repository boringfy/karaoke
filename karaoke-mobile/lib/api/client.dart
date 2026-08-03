import 'dart:convert';
import 'package:http/http.dart' as http;

import 'media_cache.dart';
import 'models.dart';

/// Thin REST client for karaoke-server. Media (audio/video/cover) are exposed
/// as URLs handed straight to the players — the server serves them with HTTP
/// range support, so seeking works.
class ApiClient {
  final String base; // e.g. http://192.168.1.50:8787
  ApiClient(this.base);

  String get _api => '$base/api/v1';

  Future<bool> ping() async {
    try {
      final r = await http
          .get(Uri.parse('$base/health'))
          .timeout(const Duration(seconds: 5));
      return r.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Library listing with offline fallback: every successful fetch is saved
  /// to the on-device cache; when the server is unreachable the cached copy
  /// is returned (with `offline: true`) and searches filter it locally.
  Future<({List<Song> songs, bool offline})> listSongs({String query = ''}) async {
    try {
      final uri = Uri.parse('$_api/songs').replace(
          queryParameters: {'limit': '500', if (query.isNotEmpty) 'q': query});
      final r = await http.get(uri).timeout(const Duration(seconds: 10));
      if (r.statusCode != 200) {
        throw Exception('list songs failed: ${r.statusCode}');
      }
      final body = jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>;
      final items = (body['items'] ?? []) as List;
      if (query.isEmpty) {
        final cache = await MediaCache.open();
        await cache.saveText('library.json', jsonEncode(items));
      }
      return (
        songs: items.map((e) => Song.fromJson(e as Map<String, dynamic>)).toList(),
        offline: false,
      );
    } catch (_) {
      final cache = await MediaCache.open();
      final raw = await cache.loadText('library.json');
      if (raw == null) rethrow;
      var songs = (jsonDecode(raw) as List)
          .map((e) => Song.fromJson(e as Map<String, dynamic>))
          .toList();
      if (query.isNotEmpty) {
        final q = query.toLowerCase();
        songs = songs
            .where((s) =>
                (s.title ?? '').toLowerCase().contains(q) ||
                (s.artist ?? '').toLowerCase().contains(q))
            .toList();
      }
      return (songs: songs, offline: true);
    }
  }

  /// Subtitle with offline fallback (same write-through pattern).
  Future<SubtitleDoc?> getSubtitle(String songId) async {
    final cache = await MediaCache.open();
    try {
      final r = await http
          .get(Uri.parse('$_api/songs/$songId/subtitle?format=json'))
          .timeout(const Duration(seconds: 10));
      if (r.statusCode == 200) {
        final raw = utf8.decode(r.bodyBytes);
        await cache.saveText('$songId.subtitle.json', raw);
        return SubtitleDoc.fromJson(jsonDecode(raw) as Map<String, dynamic>);
      }
      if (r.statusCode == 404) return null; // song truly has no subtitle
    } catch (_) {
      // fall through to cache
    }
    final raw = await cache.loadText('$songId.subtitle.json');
    if (raw == null) return null;
    try {
      return SubtitleDoc.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  Future<void> setOffset(String songId, int offsetMs) async {
    await http.patch(
      Uri.parse('$_api/songs/$songId/subtitle/offset'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'offset_ms': offsetMs}),
    );
  }

  String audioUrl(String songId, String track) =>
      '$_api/songs/$songId/audio?track=$track';
  String videoUrl(String songId) => '$_api/songs/$songId/video';
  // updatedAt busts the image cache when cover art changes.
  String coverUrl(Song s) => '$_api/songs/${s.id}/cover?v=${Uri.encodeComponent(s.updatedAt)}';
}
