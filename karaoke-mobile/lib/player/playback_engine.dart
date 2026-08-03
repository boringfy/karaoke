import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:just_audio/just_audio.dart';
import 'package:video_player/video_player.dart';

import '../api/client.dart';
import '../api/media_cache.dart';
import '../api/models.dart';

enum Track { original, instrumental }

/// Plays the original and instrumental tracks in parallel and crossfades their
/// gains so switching to "karaoke" is seamless (no seek, no gap). The audible
/// track is the clock; the muted track and the (muted) MV are nudged back into
/// sync on drift. Mirrors the desktop PlaybackEngine.
class PlaybackEngine extends ChangeNotifier {
  final _original = AudioPlayer();
  final _instrumental = AudioPlayer();
  VideoPlayerController? _video;

  Track _track = Track.original;
  bool _hasOriginal = false;
  bool _hasInstrumental = false;
  bool _videoLoops = false; // MV much shorter than audio -> repeats
  Duration _duration = Duration.zero;
  Timer? _driftTimer;
  Timer? _fadeTimer;

  Track get track => _track;
  bool get canToggle => _hasOriginal && _hasInstrumental;
  bool get hasMedia => _hasOriginal || _hasInstrumental;
  VideoPlayerController? get video => _video;
  Duration get duration => _duration;

  // The audible track is the master clock (instrumental is always present when
  // toggling; otherwise whichever single track loaded).
  AudioPlayer get _master => _hasInstrumental ? _instrumental : _original;

  // Single source of truth for play state, so the button icon and togglePlay()
  // never disagree (the underlying players' `playing` can lag a stream tick,
  // which made the first resume tap a no-op).
  bool _playing = false;
  bool get playing => _playing;

  /// Wall-clock-interpolated position (seconds) — smooth enough for the wipe.
  double get positionSec => _master.position.inMicroseconds / 1e6;

  Future<void> load(ApiClient api, Song song) async {
    await _reset();
    _hasOriginal = song.hasOriginal;
    _hasInstrumental = song.hasInstrumental;
    // Default to vocals; the user toggles to karaoke. If only an instrumental
    // exists, play that.
    _track = (_hasOriginal) ? Track.original : Track.instrumental;

    // Serve from the on-device cache when a fresh copy exists (validated
    // against the server's ETag, so replaced files auto-invalidate); otherwise
    // stream from the network while the cache fills in the background.
    final cache = await MediaCache.open();
    Future<Duration?> loadAudio(AudioPlayer player, String track) async {
      final url = api.audioUrl(song.id, track);
      // Audio always plays from a local file (downloaded now if needed):
      // seeking a network stream can stall ExoPlayer indefinitely, and audio
      // is small enough that a first-play LAN download takes ~1-3s.
      final file = await cache.fetch('${song.id}.$track', url);
      return file != null ? player.setFilePath(file.path) : player.setUrl(url);
    }

    final durs = await Future.wait([
      if (_hasOriginal) loadAudio(_original, 'original'),
      if (_hasInstrumental) loadAudio(_instrumental, 'instrumental'),
    ]);
    for (final d in durs) {
      if (d != null && d > _duration) _duration = d;
    }

    if (song.hasVideo) {
      // Best-effort: a video that can't load (server down, not yet cached)
      // must degrade to audio-only playback, never block the song.
      try {
        final url = api.videoUrl(song.id);
        final file = await cache.resolve('${song.id}.video.mp4', url);
        // mixWithOthers: the muted MV must never touch Android audio focus —
        // focus grabs/abandons at its play/complete transitions pause the
        // just_audio tracks (heard as playback freezing at the video's end).
        final opts = VideoPlayerOptions(mixWithOthers: true);
        final v = file != null
            ? VideoPlayerController.file(file, videoPlayerOptions: opts)
            : VideoPlayerController.networkUrl(Uri.parse(url), videoPlayerOptions: opts);
        await v.initialize();
        await v.setVolume(0); // audio comes from the audio players
        // MV shorter than the audio: loop it when the audio is much longer
        // (>1.5x); otherwise it ends and freezes on the last frame.
        final vd = v.value.duration;
        _videoLoops = vd > Duration.zero &&
            _duration.inMilliseconds > 1.5 * vd.inMilliseconds;
        await v.setLooping(_videoLoops);
        _video = v;
      } catch (_) {
        _video = null;
      }
    }

    _applyVolumes(immediate: true);
    notifyListeners();
  }

  void play() {
    _playing = true;
    if (_hasOriginal) _original.play(); // NB: just_audio play() completes at EOF
    if (_hasInstrumental) _instrumental.play();
    _video?.play();
    _startDrift();
    notifyListeners();
  }

  Future<void> pause() async {
    _playing = false;
    _stopDrift();
    await Future.wait([
      if (_hasOriginal) _original.pause(),
      if (_hasInstrumental) _instrumental.pause(),
      if (_video != null) _video!.pause(),
    ]);
    notifyListeners();
  }

  void togglePlay() => playing ? pause() : play();

  /// Where the MV should be for audio position [pos] (modulo when looping,
  /// clamped to the last frame otherwise).
  Duration _videoTarget(Duration pos) {
    final vd = _video?.value.duration ?? Duration.zero;
    if (vd <= Duration.zero) return pos;
    if (_videoLoops) {
      return Duration(milliseconds: pos.inMilliseconds % vd.inMilliseconds);
    }
    return pos < vd ? pos : vd;
  }

  Future<void> seek(Duration pos) async {
    await Future.wait([
      if (_hasOriginal) _original.seek(pos),
      if (_hasInstrumental) _instrumental.seek(pos),
    ]);
    final v = _video;
    if (v != null && v.value.isInitialized) {
      final vd = v.value.duration;
      final beyondEnd = !_videoLoops && vd > Duration.zero && pos >= vd;
      if (beyondEnd) {
        // Hold the final frame; never "play" a completed video (its restart/
        // complete transitions are what cause trouble).
        await v.seekTo(vd - const Duration(milliseconds: 100));
        await v.pause();
      } else {
        await v.seekTo(_videoTarget(pos));
        if (_playing) await v.play(); // was frozen at the end? moving again
      }
    }
  }

  Future<void> seekBy(int seconds) =>
      seek(_master.position + Duration(seconds: seconds));

  Future<void> restart() async {
    await seek(Duration.zero);
    play();
  }

  void setTrack(Track t) {
    if (!canToggle || t == _track) return;
    _track = t;
    _crossfade();
    notifyListeners();
  }

  void toggleTrack() =>
      setTrack(_track == Track.original ? Track.instrumental : Track.original);

  // ---- internals ---------------------------------------------------------

  void _applyVolumes({bool immediate = false}) {
    final origTarget = _track == Track.original ? 1.0 : 0.0;
    final instTarget = _track == Track.instrumental ? 1.0 : 0.0;
    if (immediate) {
      if (_hasOriginal) _original.setVolume(_hasInstrumental ? origTarget : 1.0);
      if (_hasInstrumental) _instrumental.setVolume(_hasOriginal ? instTarget : 1.0);
    }
  }

  void _crossfade() {
    _fadeTimer?.cancel();
    const steps = 8;
    const total = Duration(milliseconds: 120);
    final origStart = _original.volume, instStart = _instrumental.volume;
    final origTarget = _track == Track.original ? 1.0 : 0.0;
    final instTarget = _track == Track.instrumental ? 1.0 : 0.0;
    var i = 0;
    _fadeTimer = Timer.periodic(total ~/ steps, (tmr) {
      i++;
      final k = (i / steps).clamp(0.0, 1.0);
      _original.setVolume(origStart + (origTarget - origStart) * k);
      _instrumental.setVolume(instStart + (instTarget - instStart) * k);
      if (i >= steps) tmr.cancel();
    });
  }

  void _startDrift() {
    _stopDrift();
    // Gentle, infrequent correction. Hard-seeking the (network-streamed) video
    // on small drift causes rebuffer stutter, so only correct large drift.
    _driftTimer = Timer.periodic(const Duration(milliseconds: 1000), (_) {
      if (!_playing) return;
      final m = _master.position;
      if (canToggle) {
        final other = _hasInstrumental ? _original : _instrumental;
        if ((other.position - m).inMilliseconds.abs() > 400) other.seek(m);
      }
      final v = _video;
      if (v != null && v.value.isInitialized) {
        final vd = v.value.duration;
        if (!_videoLoops && vd > Duration.zero && m >= vd) {
          // MV over, audio continues: frozen last frame by design.
        } else {
          final target = _videoTarget(m);
          var deltaMs = (v.value.position - target).inMilliseconds;
          if (_videoLoops && vd > Duration.zero) {
            // Wrap-around distance: don't hard-seek across the loop seam.
            final half = vd.inMilliseconds ~/ 2;
            if (deltaMs > half) deltaMs -= vd.inMilliseconds;
            if (deltaMs < -half) deltaMs += vd.inMilliseconds;
          }
          if (deltaMs.abs() > 800) v.seekTo(target);
        }
      }
    });
  }

  void _stopDrift() {
    _driftTimer?.cancel();
    _driftTimer = null;
  }

  Future<void> _reset() async {
    _playing = false;
    _videoLoops = false;
    _stopDrift();
    _fadeTimer?.cancel();
    await _original.stop();
    await _instrumental.stop();
    final v = _video;
    _video = null;
    await v?.dispose();
    _hasOriginal = _hasInstrumental = false;
    _duration = Duration.zero;
  }

  /// Fully stop and release the current song (engine stays reusable).
  Future<void> stop() async {
    await _reset();
    notifyListeners();
  }

  @override
  void dispose() {
    _stopDrift();
    _fadeTimer?.cancel();
    _original.dispose();
    _instrumental.dispose();
    _video?.dispose();
    super.dispose();
  }
}
