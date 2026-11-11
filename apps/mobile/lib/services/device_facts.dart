import 'dart:io';
import 'dart:math';
import 'dart:ui' as ui;

import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'sha256.dart';

/// What this phone tells the HMRC relay for the fraud-prevention headers of the
/// MOBILE_APP_VIA_SERVER connection method (services/hmrc-relay/relay/
/// fraud_headers.py `ClientFacts`, spec v3.3; the relay adds the public IP and
/// port, the timestamps it observes and every Gov-Vendor-* header itself).
///
/// The device supplies: Gov-Client-Device-ID, -Multi-Factor, -Screens,
/// -Timezone, -User-IDs, -Window-Size, -User-Agent (os-family, os-version,
/// device-manufacturer, device-model), -Local-IPs and -Local-IPs-Timestamp,
/// plus its own version for Gov-Vendor-Version. A fact that cannot be read is
/// left out (the relay reports it as missing), never filled with a made-up
/// value. Checked against the repository's relay implementation of spec v3.3
/// on 3 Nov 2026 (HMRC's guide page refuses automated readers; HMRC's Test
/// Fraud Prevention Headers API, POST /hmrc/validate-headers on the relay, is
/// the authority to check the result against).
class DeviceFacts {
  DeviceFacts({MethodChannel? channel, Future<SharedPreferences> Function()? prefs})
      : _channel = channel ?? const MethodChannel('accnomos/device'),
        _prefs = prefs ?? SharedPreferences.getInstance;

  final MethodChannel _channel;
  final Future<SharedPreferences> Function() _prefs;

  static const _kDeviceId = 'accnomos.device_id';

  /// One random id per install, kept on the phone (never derived from
  /// hardware identifiers).
  Future<String?> deviceId() async {
    try {
      final prefs = await _prefs();
      var id = prefs.getString(_kDeviceId);
      if (id == null || id.isEmpty) {
        id = uuid4();
        await prefs.setString(_kDeviceId, id);
      }
      return id;
    } catch (_) {
      return null; // can't keep one, so don't invent a fresh id per call
    }
  }

  /// The app's own version, for a problem report ('unknown' when it cannot be read).
  Future<String> appVersion() async => (await _platform())['app_version']?.toString() ?? 'unknown';

  /// 'Android 15 Google Pixel 7', from the same facts, for a problem report.
  Future<String> userAgent() async {
    final p = await _platform();
    final parts = [
      p['os_family'],
      p['os_version'],
      p['device_manufacturer'],
      p['device_model'],
    ].where((x) => x != null && '$x'.isNotEmpty).join(' ');
    return parts.isEmpty ? 'Android' : parts;
  }

  /// `{os_family, os_version, device_manufacturer, device_model, colour_depth,
  /// app_version}` from MainActivity (Android) or AccnomosChannels.swift (iOS),
  /// or an empty map elsewhere.
  Future<Map<String, dynamic>> _platform() async {
    try {
      final raw = await _channel.invokeMethod<Map<dynamic, dynamic>>('facts');
      return raw == null ? {} : Map<String, dynamic>.from(raw);
    } catch (_) {
      return {};
    }
  }

  /// The relay's `ClientFacts` as JSON, read fresh for each call.
  Future<Map<String, dynamic>> collect({required String? accountId}) async {
    final p = await _platform();
    final facts = <String, dynamic>{'multi_factor': <Object>[]};
    final id = await deviceId();
    if (id != null) facts['device_id'] = id;

    final views = ui.PlatformDispatcher.instance.views;
    if (views.isNotEmpty) {
      final view = views.first;
      final display = view.display;
      final depth = (p['colour_depth'] as num?)?.toInt();
      if (display.size.width > 0 && display.size.height > 0 && depth != null && depth > 0) {
        facts['screens'] = [
          {
            'width': display.size.width.round(),
            'height': display.size.height.round(),
            'scaling_factor': display.devicePixelRatio,
            'colour_depth': depth,
          }
        ];
      }
      final ratio = view.devicePixelRatio;
      final w = (view.physicalSize.width / ratio).round();
      final h = (view.physicalSize.height / ratio).round();
      if (w > 0 && h > 0) facts['window_size'] = {'width': w, 'height': h};
    }

    facts['timezone'] = utcOffset(DateTime.now().timeZoneOffset);
    if (accountId != null && accountId.isNotEmpty) {
      facts['user_ids'] = {'accnomos': sha256Hex(accountId)};
    }
    final ua = {
      'os_family': p['os_family'],
      'os_version': p['os_version'],
      'device_manufacturer': p['device_manufacturer'],
      'device_model': p['device_model'],
    };
    if (ua.values.every((v) => v is String && v.isNotEmpty)) facts['user_agent'] = ua;

    final ips = await localIps();
    if (ips.isNotEmpty) {
      facts['local_ips'] = ips;
      facts['local_ips_timestamp'] = hmrcTimestamp(DateTime.now().toUtc());
    }
    final version = p['app_version'];
    if (version is String && version.isNotEmpty) {
      final product = Platform.isIOS ? 'accnomos-ios' : 'accnomos-android';
      facts['vendor_versions'] = {product: version};
    }
    return facts;
  }

  /// Every non-loopback address on the phone's interfaces.
  static Future<List<String>> localIps() async {
    try {
      final interfaces = await NetworkInterface.list(includeLoopback: false);
      return [
        for (final i in interfaces)
          for (final a in i.addresses)
            if (!a.isLoopback) a.address.split('%').first,
      ].take(20).toList();
    } catch (_) {
      return const [];
    }
  }
}

/// `UTC+01:00` / `UTC-05:30`, the Gov-Client-Timezone format.
String utcOffset(Duration offset) {
  final mins = offset.inMinutes;
  final abs = mins.abs();
  final hh = (abs ~/ 60).toString().padLeft(2, '0');
  final mm = (abs % 60).toString().padLeft(2, '0');
  return 'UTC${mins >= 0 ? '+' : '-'}$hh:$mm';
}

/// `2026-11-03T09:12:45.123Z` (yyyy-MM-ddThh:mm:ss.sssZ, UTC).
String hmrcTimestamp(DateTime utc) {
  final u = utc.toUtc();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${u.year.toString().padLeft(4, '0')}-${two(u.month)}-${two(u.day)}'
      'T${two(u.hour)}:${two(u.minute)}:${two(u.second)}.'
      '${u.millisecond.toString().padLeft(3, '0')}Z';
}

/// A random version-4 UUID.
String uuid4([Random? random]) {
  final r = random ?? Random.secure();
  final b = List<int>.generate(16, (_) => r.nextInt(256));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  final hex = b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-'
      '${hex.substring(16, 20)}-${hex.substring(20)}';
}
