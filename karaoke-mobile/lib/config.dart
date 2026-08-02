import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Holds the LAN address of karaoke-server, persisted across launches.
/// e.g. http://192.168.1.50:8787
class AppConfig extends ChangeNotifier {
  static const _key = 'server_base';
  String _serverBase = '';

  String get serverBase => _serverBase;
  bool get isConfigured => _serverBase.isNotEmpty;

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    _serverBase = prefs.getString(_key) ?? '';
    notifyListeners();
  }

  Future<void> setServerBase(String value) async {
    var v = value.trim();
    if (v.isEmpty) return;
    if (!v.startsWith('http://') && !v.startsWith('https://')) v = 'http://$v';
    // Default port if the user typed a bare host/IP.
    final uri = Uri.parse(v);
    if (uri.hasPort == false) v = '$v:8787';
    _serverBase = v.replaceAll(RegExp(r'/+$'), '');
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, _serverBase);
    notifyListeners();
  }

  Future<void> clear() async {
    _serverBase = '';
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_key);
    notifyListeners();
  }
}
