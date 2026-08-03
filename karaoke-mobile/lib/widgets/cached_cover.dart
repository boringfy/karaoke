import 'dart:io';

import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/media_cache.dart';
import '../api/models.dart';

/// Cover art backed by the on-device cache. The cache key embeds the song's
/// updated_at, so covers are immutable once fetched (no revalidation) and
/// still render when the server is down. [offline] skips network attempts.
class CachedCover extends StatelessWidget {
  final ApiClient api;
  final Song song;
  final bool offline;
  final BoxFit fit;
  final Widget fallback;

  const CachedCover({
    super.key,
    required this.api,
    required this.song,
    required this.fallback,
    this.offline = false,
    this.fit = BoxFit.cover,
  });

  Future<File?> _load() async {
    if (!song.hasCover) return null;
    final cache = await MediaCache.open();
    final ver = song.updatedAt.replaceAll(RegExp(r'[^0-9A-Za-z]'), '');
    return cache.immutable(
      'cover_${song.id}@$ver',
      api.coverUrl(song),
      allowNetwork: !offline,
    );
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<File?>(
      future: _load(),
      builder: (context, snap) {
        final f = snap.data;
        if (f == null) return fallback;
        return Image.file(f, fit: fit, errorBuilder: (_, __, ___) => fallback);
      },
    );
  }
}
