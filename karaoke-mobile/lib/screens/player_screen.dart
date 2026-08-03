import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:video_player/video_player.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../player/playback_engine.dart';
import '../widgets/cached_cover.dart';
import '../widgets/lyrics_view.dart';

class PlayerScreen extends StatefulWidget {
  final ApiClient api;
  final Song song;
  const PlayerScreen({super.key, required this.api, required this.song});
  @override
  State<PlayerScreen> createState() => _PlayerScreenState();
}

class _PlayerScreenState extends State<PlayerScreen> {
  late final PlaybackEngine _engine;
  SubtitleDoc? _subtitle;
  bool _loading = true;
  String? _error;
  Timer? _tick;
  double _pos = 0;
  double? _drag;

  @override
  void initState() {
    super.initState();
    _engine = context.read<PlaybackEngine>();
    _start();
    _tick = Timer.periodic(const Duration(milliseconds: 200), (_) {
      if (mounted && _drag == null) setState(() => _pos = _engine.positionSec);
    });
  }

  Future<void> _start() async {
    try {
      final subF = widget.song.hasSubtitle
          ? widget.api.getSubtitle(widget.song.id)
          : Future<SubtitleDoc?>.value(null);
      await _engine.load(widget.api, widget.song);
      _subtitle = await subF;
      if (!mounted) return;
      setState(() => _loading = false);
      _engine.play();
    } catch (e) {
      if (mounted) setState(() {
        _loading = false;
        _error = '$e';
      });
    }
  }

  @override
  void dispose() {
    _tick?.cancel();
    _engine.stop(); // leaving the player stops playback
    super.dispose();
  }

  String _fmt(double s) {
    final d = Duration(seconds: s.round());
    final m = d.inMinutes, sec = d.inSeconds % 60;
    return '$m:${sec.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final dur = _engine.duration.inMicroseconds / 1e6;
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        fit: StackFit.expand,
        children: [
          _background(),
          const DecoratedBox(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.center,
                end: Alignment.bottomCenter,
                colors: [Colors.transparent, Color(0xCC000000)],
              ),
            ),
          ),
          // Lyrics occupy the lower-middle band.
          if (_subtitle != null)
            Positioned(
              left: 0,
              right: 0,
              bottom: 130,
              height: 220,
              child: LyricsView(
                engine: _engine,
                subtitle: _subtitle!,
                offsetMs: widget.song.subtitleOffsetMs,
              ),
            ),
          if (_loading)
            const Center(child: CircularProgressIndicator()),
          if (_error != null)
            Center(
                child: Padding(
              padding: const EdgeInsets.all(24),
              child: Text('Playback error:\n$_error',
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: Color(0xFFE5586A))),
            )),
          SafeArea(
            child: Align(
              alignment: Alignment.topLeft,
              child: IconButton(
                icon: const Icon(Icons.keyboard_arrow_down, size: 32),
                onPressed: () => Navigator.of(context).pop(),
              ),
            ),
          ),
          _transport(dur),
        ],
      ),
    );
  }

  Widget _background() {
    return AnimatedBuilder(
      animation: _engine,
      builder: (_, __) {
        final v = _engine.video;
        if (v != null && v.value.isInitialized) {
          return FittedBox(
            fit: BoxFit.cover,
            child: SizedBox(
              width: v.value.size.width,
              height: v.value.size.height,
              child: VideoPlayer(v),
            ),
          );
        }
        if (widget.song.hasCover) {
          return CachedCover(
            api: widget.api,
            song: widget.song,
            fallback: const ColoredBox(color: Color(0xFF0F1115)),
          );
        }
        return const ColoredBox(color: Color(0xFF0F1115));
      },
    );
  }

  Widget _transport(double dur) {
    return Positioned(
      left: 0,
      right: 0,
      bottom: 0,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  Text(_fmt(_drag ?? _pos), style: const TextStyle(fontSize: 12)),
                  Expanded(
                    child: Slider(
                      value: (_drag ?? _pos).clamp(0.0, dur <= 0 ? 1.0 : dur).toDouble(),
                      max: dur <= 0 ? 1.0 : dur,
                      onChanged: (v) => setState(() => _drag = v),
                      onChangeEnd: (v) {
                        _engine.seek(Duration(milliseconds: (v * 1000).round()));
                        setState(() {
                          _pos = v;
                          _drag = null;
                        });
                      },
                    ),
                  ),
                  Text(_fmt(dur), style: const TextStyle(fontSize: 12)),
                ],
              ),
              AnimatedBuilder(
                animation: _engine,
                builder: (_, __) => Row(
                  mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                  children: [
                    IconButton(
                      icon: const Icon(Icons.replay),
                      tooltip: 'Restart',
                      onPressed: () => _engine.restart(),
                    ),
                    IconButton(
                      icon: const Icon(Icons.replay_10),
                      onPressed: () => _engine.seekBy(-10),
                    ),
                    IconButton(
                      iconSize: 56,
                      icon: Icon(_engine.playing
                          ? Icons.pause_circle_filled
                          : Icons.play_circle_fill),
                      onPressed: () => _engine.togglePlay(),
                    ),
                    IconButton(
                      icon: const Icon(Icons.forward_10),
                      onPressed: () => _engine.seekBy(10),
                    ),
                    // Karaoke ⇄ original toggle (only when both tracks exist).
                    _engine.canToggle
                        ? TextButton(
                            onPressed: () => _engine.toggleTrack(),
                            child: Text(
                              _engine.track == Track.instrumental
                                  ? 'Karaoke'
                                  : 'Original',
                              style: const TextStyle(fontWeight: FontWeight.bold),
                            ),
                          )
                        : const SizedBox(width: 48),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
