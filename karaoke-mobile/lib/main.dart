import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'config.dart';
import 'player/playback_engine.dart';
import 'screens/library_screen.dart';
import 'screens/server_setup_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const KaraokeApp());
}

class KaraokeApp extends StatelessWidget {
  const KaraokeApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => AppConfig()),
        ChangeNotifierProvider(create: (_) => PlaybackEngine()),
      ],
      child: MaterialApp(
        title: 'Karaoke',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          brightness: Brightness.dark,
          scaffoldBackgroundColor: const Color(0xFF0F1115),
          colorScheme: const ColorScheme.dark(primary: Color(0xFF6C8CFF)),
          useMaterial3: true,
        ),
        home: const _Root(),
      ),
    );
  }
}

class _Root extends StatefulWidget {
  const _Root();
  @override
  State<_Root> createState() => _RootState();
}

class _RootState extends State<_Root> {
  late final Future<void> _loaded = context.read<AppConfig>().load();

  @override
  Widget build(BuildContext context) {
    return FutureBuilder(
      future: _loaded,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Scaffold(body: Center(child: CircularProgressIndicator()));
        }
        final configured = context.watch<AppConfig>().isConfigured;
        return configured ? const LibraryScreen() : const ServerSetupScreen();
      },
    );
  }
}
