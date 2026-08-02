import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/client.dart';
import '../config.dart';

class ServerSetupScreen extends StatefulWidget {
  const ServerSetupScreen({super.key});
  @override
  State<ServerSetupScreen> createState() => _ServerSetupScreenState();
}

class _ServerSetupScreenState extends State<ServerSetupScreen> {
  final _ctrl = TextEditingController();
  bool _busy = false;
  String? _error;

  String _normalize(String v) {
    v = v.trim();
    if (v.isEmpty) return v;
    if (!v.startsWith('http://') && !v.startsWith('https://')) v = 'http://$v';
    final uri = Uri.parse(v);
    if (!uri.hasPort) v = '$v:8787';
    return v.replaceAll(RegExp(r'/+$'), '');
  }

  Future<void> _connect() async {
    final url = _normalize(_ctrl.text);
    if (url.isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final ok = await ApiClient(url).ping();
    if (!mounted) return;
    if (ok) {
      await context.read<AppConfig>().setServerBase(url);
    } else {
      setState(() {
        _busy = false;
        _error = "Couldn't reach $url — check the IP, port, and that the "
            'server is bound to 0.0.0.0.';
      });
    }
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 460),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Icon(Icons.mic_external_on, size: 56, color: Color(0xFF6C8CFF)),
                const SizedBox(height: 16),
                const Text('Connect to karaoke-server',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                const Text('Enter your server\'s LAN address.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.white70)),
                const SizedBox(height: 24),
                TextField(
                  controller: _ctrl,
                  autofocus: true,
                  keyboardType: TextInputType.url,
                  onSubmitted: (_) => _connect(),
                  decoration: const InputDecoration(
                    labelText: 'Server address',
                    hintText: '192.168.1.50:8787',
                    border: OutlineInputBorder(),
                  ),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!, style: const TextStyle(color: Color(0xFFE5586A))),
                ],
                const SizedBox(height: 20),
                FilledButton(
                  onPressed: _busy ? null : _connect,
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    child: _busy
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : const Text('Connect'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
