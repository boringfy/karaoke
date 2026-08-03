import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/client.dart';
import '../api/media_cache.dart';
import '../api/models.dart';
import '../config.dart';
import '../widgets/cached_cover.dart';
import 'player_screen.dart';

class LibraryScreen extends StatefulWidget {
  const LibraryScreen({super.key});
  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends State<LibraryScreen> {
  late ApiClient _api;
  final _searchCtrl = TextEditingController();
  Future<({List<Song> songs, bool offline})>? _future;
  String _query = '';

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _api = ApiClient(context.read<AppConfig>().serverBase);
    _future ??= _api.listSongs();
  }

  Future<void> _refresh() async {
    setState(() => _future = _api.listSongs(query: _query));
    await _future;
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Songs'),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings),
            tooltip: 'Change server',
            onPressed: () => context.read<AppConfig>().clear(),
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(56),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
            child: TextField(
              controller: _searchCtrl,
              onChanged: (v) => _query = v,
              onSubmitted: (_) => _refresh(),
              decoration: InputDecoration(
                hintText: 'Search song or singer…',
                prefixIcon: const Icon(Icons.search),
                isDense: true,
                filled: true,
                border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(24), borderSide: BorderSide.none),
              ),
            ),
          ),
        ),
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: FutureBuilder<({List<Song> songs, bool offline})>(
          future: _future,
          builder: (context, snap) {
            if (snap.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snap.hasError) {
              return ListView(children: const [
                SizedBox(height: 100),
                Center(
                    child: Text('Server unreachable and nothing cached yet.',
                        style: TextStyle(color: Color(0xFFE5586A)))),
                SizedBox(height: 8),
                Center(
                    child: Text('Play songs once while online to make them\navailable offline.',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: Colors.white54))),
              ]);
            }
            final data = snap.data!;
            final songs = data.songs;
            return Column(children: [
              if (data.offline)
                Container(
                  width: double.infinity,
                  color: const Color(0xFF6b5310),
                  padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 14),
                  child: const Text(
                    'Offline — showing cached library. Songs marked ✓ are fully cached.',
                    style: TextStyle(fontSize: 13),
                  ),
                ),
              Expanded(
                child: songs.isEmpty
                    ? ListView(children: const [
                        SizedBox(height: 120),
                        Center(
                            child: Text('No songs. Add some from the desktop app.',
                                style: TextStyle(color: Colors.white54))),
                      ])
                    : ListView.separated(
                        itemCount: songs.length,
                        separatorBuilder: (_, __) => const Divider(height: 1),
                        itemBuilder: (_, i) =>
                            _SongTile(api: _api, song: songs[i], offline: data.offline),
                      ),
              ),
            ]);
          },
        ),
      ),
    );
  }
}

class _SongTile extends StatelessWidget {
  final ApiClient api;
  final Song song;
  final bool offline;
  const _SongTile({required this.api, required this.song, required this.offline});

  Future<bool> _isCached() async {
    final cache = await MediaCache.open();
    return await cache.hasComplete('${song.id}.original') ||
        await cache.hasComplete('${song.id}.instrumental');
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<bool>(
      future: _isCached(),
      builder: (context, snap) {
        final cached = snap.data ?? false;
        // Offline, an uncached song cannot play — grey it out.
        final playable = song.playable && (!offline || cached);
        return ListTile(
          leading: ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: SizedBox(
              width: 48,
              height: 48,
              child: CachedCover(
                  api: api, song: song, offline: offline, fallback: const _CoverFallback()),
            ),
          ),
          title: Text(song.title ?? '(untitled)',
              maxLines: 1, overflow: TextOverflow.ellipsis),
          subtitle: Text(song.artist ?? '', maxLines: 1, overflow: TextOverflow.ellipsis),
          trailing: Row(mainAxisSize: MainAxisSize.min, children: [
            if (cached)
              const Padding(
                padding: EdgeInsets.only(right: 8),
                child: Icon(Icons.offline_pin, size: 18, color: Colors.white38),
              ),
            if (playable)
              const Icon(Icons.play_circle_fill, size: 32, color: Color(0xFF6C8CFF))
            else
              Text(offline && song.playable ? 'not cached' : song.status,
                  style: const TextStyle(color: Colors.white38, fontSize: 12)),
          ]),
          enabled: playable,
          onTap: playable
              ? () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => PlayerScreen(api: api, song: song),
                  ))
              : null,
        );
      },
    );
  }
}

class _CoverFallback extends StatelessWidget {
  const _CoverFallback();
  @override
  Widget build(BuildContext context) => Container(
      color: const Color(0xFF1F232D),
      child: const Icon(Icons.music_note, color: Colors.white38));
}
