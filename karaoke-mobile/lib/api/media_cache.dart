import 'dart:async';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

/// On-device cache for streamed media (audio tracks, MV) so repeat plays load
/// instantly from disk. Freshness is validated against the server's ETag /
/// Last-Modified (a 1-byte ranged GET — the server has no HEAD): the server
/// derives the ETag from the file's mtime+size, so replacing a song's audio or
/// video on the server automatically invalidates the cached copy here.
class MediaCache {
  final Directory root;
  MediaCache._(this.root);

  static const _maxBytes = 2 * 1024 * 1024 * 1024; // 2 GB
  static final Set<String> _filling = {}; // one background fill per key
  static MediaCache? _instance;

  static Future<MediaCache> open() async {
    if (_instance != null) return _instance!;
    final base = await getApplicationCacheDirectory();
    final dir = Directory('${base.path}/media');
    await dir.create(recursive: true);
    final cache = MediaCache._(dir);
    unawaited(cache._trim());
    _instance = cache;
    return cache;
  }

  File _data(String key) => File('${root.path}/$key');
  File _meta(String key) => File('${root.path}/$key.meta');
  File _part(String key) => File('${root.path}/$key.part');

  /// The server-side identity of [url] (etag, falling back to last-modified),
  /// or null when the server can't be reached quickly.
  Future<String?> _remoteTag(String url) async {
    try {
      final req = http.Request('GET', Uri.parse(url))
        ..headers['Range'] = 'bytes=0-0';
      final res = await http.Client()
          .send(req)
          .timeout(const Duration(seconds: 4));
      await res.stream.drain();
      return res.headers['etag'] ?? res.headers['last-modified'];
    } catch (_) {
      return null;
    }
  }

  /// Fetch [url] into the cache NOW and return the file (used for audio:
  /// playing local files makes seeking instant and immune to network stalls;
  /// audio is small so the first-play download is fast on a LAN). Falls back
  /// to a stale complete copy, or null when nothing can be served locally.
  Future<File?> fetch(String key, String url) async {
    final data = _data(key);
    final meta = _meta(key);
    final haveComplete = await data.exists() && await meta.exists();
    final tag = await _remoteTag(url);
    if (tag == null) return haveComplete ? data : null;
    if (haveComplete && (await meta.readAsString()) == tag) return data;
    await _delete(key);
    await _fill(key, url, tag); // direct: no background queue, no delay
    return await data.exists() ? data : null;
  }

  /// Resolve [url] for playback. Returns a local file when a fresh (or, if the
  /// server is unreachable, stale-but-complete) copy exists; otherwise null —
  /// play from the network while the cache fills in the background for next
  /// time.
  Future<File?> resolve(String key, String url) async {
    final data = _data(key);
    final meta = _meta(key);
    final haveComplete = await data.exists() && await meta.exists();
    final tag = await _remoteTag(url);

    if (tag == null) {
      // Offline / server busy: a complete cached copy is better than nothing.
      return haveComplete ? data : null;
    }
    if (haveComplete && (await meta.readAsString()) == tag) {
      return data; // fresh hit
    }
    // Stale or absent: clear leftovers; caller streams from network.
    await _delete(key);
    unawaited(_enqueueFill(key, url, tag));
    return null;
  }

  /// Fills run one at a time, and politely: a burst of parallel downloads
  /// (audio + a large MV) can saturate the device's WiFi and starve the
  /// actual playback streams, stalling seeks for many seconds.
  static Future<void> _fillChain = Future.value();

  Future<void> _enqueueFill(String key, String url, String tag) {
    final task = _fillChain
        .then((_) => Future.delayed(const Duration(seconds: 5)))
        .then((_) => _fill(key, url, tag));
    _fillChain = task.catchError((_) {});
    return task;
  }

  Future<void> _fill(String key, String url, String tag) async {
    if (_filling.contains(key)) return;
    _filling.add(key);
    final part = _part(key);
    try {
      final res = await http.Client()
          .send(http.Request('GET', Uri.parse(url)))
          .timeout(const Duration(minutes: 30));
      if (res.statusCode != 200) return;
      final sink = part.openWrite();
      await res.stream.pipe(sink);
      // The tag was read just before the download; if the file changed on the
      // server mid-download the next resolve() re-validates anyway.
      await part.rename(_data(key).path);
      await _meta(key).writeAsString(tag);
    } catch (_) {
      try {
        if (await part.exists()) await part.delete();
      } catch (_) {}
    } finally {
      _filling.remove(key);
    }
  }

  Future<void> _delete(String key) async {
    for (final f in [_data(key), _meta(key), _part(key)]) {
      try {
        if (await f.exists()) await f.delete();
      } catch (_) {}
    }
  }

  /// Drop oldest entries when the cache outgrows its budget.
  Future<void> _trim() async {
    try {
      final files = await root
          .list()
          .where((e) => e is File && !e.path.endsWith('.meta'))
          .cast<File>()
          .toList();
      var total = 0;
      final stats = <(File, FileStat)>[];
      for (final f in files) {
        final st = await f.stat();
        total += st.size;
        stats.add((f, st));
      }
      if (total <= _maxBytes) return;
      stats.sort((a, b) => a.$2.modified.compareTo(b.$2.modified));
      for (final (f, st) in stats) {
        if (total <= _maxBytes) break;
        try {
          await f.delete();
          final meta = File('${f.path}.meta');
          if (await meta.exists()) await meta.delete();
          total -= st.size;
        } catch (_) {}
      }
    } catch (_) {}
  }
}
