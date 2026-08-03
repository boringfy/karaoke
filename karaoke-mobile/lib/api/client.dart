import 'dart:convert';
import 'package:http/http.dart' as http;

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

  Future<List<Song>> listSongs({String query = ''}) async {
    final uri = Uri.parse('$_api/songs')
        .replace(queryParameters: {'limit': '500', if (query.isNotEmpty) 'q': query});
    final r = await http.get(uri).timeout(const Duration(seconds: 15));
    if (r.statusCode != 200) {
      throw Exception('list songs failed: ${r.statusCode}');
    }
    final body = jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>;
    return ((body['items'] ?? []) as List)
        .map((e) => Song.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<SubtitleDoc?> getSubtitle(String songId) async {
    final r = await http
        .get(Uri.parse('$_api/songs/$songId/subtitle?format=json'))
        .timeout(const Duration(seconds: 15));
    if (r.statusCode != 200) return null;
    return SubtitleDoc.fromJson(
        jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>);
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
