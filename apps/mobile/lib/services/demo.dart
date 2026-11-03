import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// A live demo session on the runtime: the same sandbox the website's
/// "Try the demo" / "Try the personal demo" start (apps/web/src/lib/demo.ts,
/// services/runtime/app/demo.py). No Microsoft sign-in: every runtime call
/// carries `X-Demo-Session` instead of a Graph token, and the app's own
/// OneDrive calls go to the runtime's Graph look-alike at
/// `<runtime>/demo/graph/v1.0`, over that session's in-memory sample books.
///
/// `kind` is `company` (Bramblewood Joinery, fictional) or `personal` (a
/// fictional household). The session id is kept on this phone so the demo
/// survives an app restart; the runtime forgets an idle session after two
/// hours, and the app then starts a fresh one of the same kind.
@immutable
class DemoInfo {
  const DemoInfo({
    required this.session,
    required this.kind,
    required this.runtimeUrl,
    this.business = '',
    this.user = 'demo@accnomos.example',
  });

  final String session;

  /// `company` or `personal`.
  final String kind;

  /// The runtime that holds this session (its `/demo/graph/v1.0` too).
  final String runtimeUrl;

  /// The fictional business or household the runtime named.
  final String business;

  /// The sandbox's own fixed user (approvals are recorded as this user).
  final String user;

  bool get household => kind == 'personal';

  /// The label above every tab, as the web's demo bar.
  String get label => household
      ? 'SAMPLE — FICTIONAL HOUSEHOLD'
      : 'SAMPLE — FICTIONAL COMPANY';

  /// The Graph look-alike for this session.
  String get graphBase => '$runtimeUrl/demo/graph/v1.0';
}

/// The runtime would not start a demo; [message] is safe to show.
class DemoException implements Exception {
  DemoException(this.message);
  final String message;

  @override
  String toString() => message;
}

class Demo {
  Demo._();

  static const header = 'X-Demo-Session';
  static const _kSession = 'accnomos.demo.session';
  static const _kKind = 'accnomos.demo.kind';
  static const _kRuntime = 'accnomos.demo.runtime';
  static const _kBusiness = 'accnomos.demo.business';
  static const _kUser = 'accnomos.demo.user';
  static const _timeout = Duration(seconds: 90);

  /// The running demo, or null.
  static final ValueNotifier<DemoInfo?> state = ValueNotifier(null);

  static DemoInfo? get current => state.value;
  static bool get active => state.value != null;

  /// Test transport.
  @visibleForTesting
  static http.Client? httpOverride;

  static http.Client get _http => httpOverride ?? http.Client();

  /// Starts a demo of [kind] on [runtimeUrl]; a running demo is dropped
  /// first (the runtime does that when the old id rides along).
  static Future<DemoInfo> start(String runtimeUrl, String kind) async {
    final old = current;
    final http.Response res;
    try {
      res = await _http
          .post(Uri.parse('$runtimeUrl/demo/session?kind=$kind'),
              headers: {if (old != null) header: old.session})
          .timeout(_timeout);
    } on TimeoutException {
      throw DemoException(
          'The demo took too long to start. Check your connection and try again.');
    } catch (_) {
      throw DemoException(
          'Could not reach Accnomos. Check your connection and try again.');
    }
    if (res.statusCode == 429) {
      throw DemoException(
          'Too many demos started from this network just now. Try again in a minute.');
    }
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw DemoException(res.statusCode == 404 || res.statusCode == 401
          ? 'The demo is switched off on this server. Sign in with Microsoft instead.'
          : 'The demo could not be prepared just now. Try again in a minute.');
    }
    final Map<String, dynamic> body;
    try {
      body = json.decode(res.body) as Map<String, dynamic>;
    } catch (_) {
      throw DemoException('The demo could not be prepared just now.');
    }
    final id = body['session'];
    if (id is! String || id.isEmpty) {
      throw DemoException('The demo could not be prepared just now.');
    }
    final info = DemoInfo(
      session: id,
      kind: (body['kind'] ?? kind).toString(),
      runtimeUrl: runtimeUrl,
      business: (body['business'] ?? '').toString(),
      user: (body['user'] ?? 'demo@accnomos.example').toString(),
    );
    await _save(info);
    state.value = info;
    return info;
  }

  /// Ends the demo here and on the runtime (best effort).
  static Future<void> end() async {
    final old = current;
    state.value = null;
    await _save(null);
    if (old == null) return;
    try {
      await _http
          .delete(Uri.parse('${old.runtimeUrl}/demo/session'),
              headers: {header: old.session})
          .timeout(const Duration(seconds: 10));
    } catch (_) {
      // The runtime forgets it after two idle hours anyway.
    }
  }

  /// At launch: the demo kept on this phone, if any. A session the runtime
  /// no longer knows is replaced by a fresh one of the same kind; when that
  /// fails too, the demo ends and the app opens on Welcome.
  static Future<DemoInfo?> restore() async {
    final prefs = await SharedPreferences.getInstance();
    final id = prefs.getString(_kSession);
    final kind = prefs.getString(_kKind);
    final runtime = prefs.getString(_kRuntime);
    if (id == null || kind == null || runtime == null) return null;
    final saved = DemoInfo(
      session: id,
      kind: kind,
      runtimeUrl: runtime,
      business: prefs.getString(_kBusiness) ?? '',
      user: prefs.getString(_kUser) ?? 'demo@accnomos.example',
    );
    try {
      final alive = await _http
          .get(Uri.parse('$runtime/demo/session'), headers: {header: id})
          .timeout(const Duration(seconds: 15));
      if (alive.statusCode == 200) {
        state.value = saved;
        return saved;
      }
    } catch (_) {
      // Offline: keep the saved demo; the screens say they cannot load.
      state.value = saved;
      return saved;
    }
    return renew(saved);
  }

  /// The runtime said the session is gone (401/404 with the demo header):
  /// a fresh demo of the same kind, or none.
  static Future<DemoInfo?> renew([DemoInfo? from]) async {
    final old = from ?? current;
    if (old == null) return null;
    try {
      state.value = null;
      return await start(old.runtimeUrl, old.kind);
    } catch (_) {
      await end();
      return null;
    }
  }

  static Future<void> _save(DemoInfo? info) async {
    final prefs = await SharedPreferences.getInstance();
    if (info == null) {
      for (final k in [_kSession, _kKind, _kRuntime, _kBusiness, _kUser]) {
        await prefs.remove(k);
      }
      return;
    }
    await prefs.setString(_kSession, info.session);
    await prefs.setString(_kKind, info.kind);
    await prefs.setString(_kRuntime, info.runtimeUrl);
    await prefs.setString(_kBusiness, info.business);
    await prefs.setString(_kUser, info.user);
  }

  /// Tests only: set or clear the demo without the runtime.
  @visibleForTesting
  static void debugSet(DemoInfo? info) => state.value = info;
}
