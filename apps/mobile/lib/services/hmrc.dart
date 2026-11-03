import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

import 'demo.dart';
import 'device_facts.dart';
import 'sha256.dart';

/// HMRC MTD VAT (sandbox) through the stateless relay (services/hmrc-relay),
/// the Android twin of `apps/web/src/lib/hmrc.ts`.
///
/// * OAuth is PKCE: the verifier never leaves this phone. The relay's callback
///   sends the browser to accnomos.com/auth/hmrc-app.html, which hands the
///   one-time code back to the app by its own URL scheme
///   (`com.accnomos.app://hmrc/callback`, MainActivity); the app then swaps
///   code + verifier for tokens at POST /hmrc/exchange.
/// * Tokens live in memory only (like the web's sessionStorage): closing the
///   app ends the HMRC session.
/// * Every VAT call names the MOBILE_APP_VIA_SERVER connection method and
///   carries this phone's facts ([DeviceFacts]); the relay adds the rest of the
///   fraud-prevention headers.
/// * In a demo nothing reaches HMRC, not even the sandbox: connect, the
///   obligations and the submission are simulated, and the receipt says so.
class Obligation {
  Obligation({
    required this.periodKey,
    required this.start,
    required this.end,
    required this.due,
    required this.status,
    this.received,
  });

  final String periodKey;
  final String start;
  final String end;
  final String due;
  final String status; // O open, F fulfilled
  final String? received;

  bool get open => status == 'O';

  factory Obligation.fromJson(Map<String, dynamic> j) => Obligation(
        periodKey: (j['periodKey'] ?? '').toString(),
        start: (j['start'] ?? '').toString(),
        end: (j['end'] ?? '').toString(),
        due: (j['due'] ?? '').toString(),
        status: (j['status'] ?? 'O').toString(),
        received: j['received']?.toString(),
      );

  Map<String, dynamic> toJson() => {
        'periodKey': periodKey,
        'start': start,
        'end': end,
        'due': due,
        'status': status,
        if (received != null) 'received': received,
      };

  Obligation fulfilled() => Obligation(
      periodKey: periodKey, start: start, end: end, due: due, status: 'F', received: received);

  static List<Obligation> listFrom(Object? hmrcBody) {
    final raw = hmrcBody is Map ? hmrcBody['obligations'] : null;
    if (raw is! List) return const [];
    return [
      for (final o in raw)
        if (o is Map) Obligation.fromJson(Map<String, dynamic>.from(o)),
    ];
  }
}

class SubmitReceipt {
  SubmitReceipt({
    required this.processingDate,
    required this.formBundleNumber,
    this.paymentIndicator,
    this.chargeRefNumber,
  });

  final String processingDate;
  final String formBundleNumber;
  final String? paymentIndicator;
  final String? chargeRefNumber;

  factory SubmitReceipt.fromJson(Map<String, dynamic> j) => SubmitReceipt(
        processingDate: (j['processingDate'] ?? '').toString(),
        formBundleNumber: (j['formBundleNumber'] ?? '').toString(),
        paymentIndicator: j['paymentIndicator']?.toString(),
        chargeRefNumber: j['chargeRefNumber']?.toString(),
      );

  Map<String, dynamic> toJson() => {
        'processingDate': processingDate,
        'formBundleNumber': formBundleNumber,
        if (paymentIndicator != null) 'paymentIndicator': paymentIndicator,
        if (chargeRefNumber != null) 'chargeRefNumber': chargeRefNumber,
      };
}

/// The relay's answer envelope for every VAT call.
class RelayResult {
  RelayResult({
    required this.hmrc,
    this.sentHeaders = const {},
    this.missing = const [],
    this.correlationId,
    this.receiptId,
    this.receiptTimestamp,
  });

  final Object? hmrc;
  final Map<String, String> sentHeaders;
  final List<String> missing;
  final String? correlationId;
  final String? receiptId;
  final String? receiptTimestamp;

  factory RelayResult.fromJson(Map<String, dynamic> j) => RelayResult(
        hmrc: j['hmrc'],
        sentHeaders: {
          for (final e in ((j['sent_headers'] as Map?) ?? const {}).entries)
            e.key.toString(): e.value.toString(),
        },
        missing: [for (final m in (j['fraud_headers_missing'] as List?) ?? const []) m.toString()],
        correlationId: j['correlation_id']?.toString(),
        receiptId: j['receipt_id']?.toString(),
        receiptTimestamp: j['receipt_timestamp']?.toString(),
      );
}

class RelayException implements Exception {
  RelayException(this.message, this.status);
  final String message;
  final int status;
  @override
  String toString() => message;
}

/// The HMRC session has gone (never connected, or the refresh failed).
class HmrcAuthException implements Exception {
  HmrcAuthException(this.message);
  final String message;
  @override
  String toString() => message;
}

class HmrcTokens {
  HmrcTokens(this.accessToken, this.refreshToken, this.expiresAt);
  final String accessToken;
  final String refreshToken;
  final DateTime expiresAt;
}

/// Shown on the receipt and saved in it, so a simulated submission can never
/// pass for a real one (the web's `DEMO_SUBMISSION`).
const demoSubmission = 'Demo — submission simulated';

/// The sample books' fictional VAT number (the web's `DEMO_VRN`).
const demoVrn = '123456789';

/// The legal declaration HMRC requires before a VAT return is sent
/// (word for word as the web's ConnectHmrc.tsx).
const vatDeclaration =
    'When you submit this VAT information you are making a legal declaration that the information is true and complete. A false declaration can result in prosecution.';

class Hmrc {
  Hmrc({
    required this.relayUrl,
    http.Client? client,
    DeviceFacts? facts,
    MethodChannel? channel,
    Future<bool> Function(Uri)? openUrl,
    Future<SharedPreferences> Function()? prefs,
    DateTime Function()? now,
  })  : _client = client ?? http.Client(),
        _facts = facts ?? DeviceFacts(),
        _channel = channel ?? const MethodChannel('accnomos/hmrc'),
        _open = openUrl ?? ((u) => launchUrl(u, mode: LaunchMode.externalApplication)),
        _prefs = prefs ?? SharedPreferences.getInstance,
        _now = now ?? DateTime.now;

  final String relayUrl;
  final http.Client _client;
  final DeviceFacts _facts;
  final MethodChannel _channel;
  final Future<bool> Function(Uri) _open;
  final Future<SharedPreferences> Function() _prefs;
  final DateTime Function() _now;

  /// Where the relay sends the browser after HMRC (an allowed origin already).
  static const redirectTo = 'https://accnomos.com/auth/hmrc-app.html';
  static const connectionMethod = 'MOBILE_APP_VIA_SERVER';
  static const _kPending = 'accnomos.hmrc.pending';
  static const _kVrn = 'accnomos.business.vrn';
  static const _demoToken = 'demo-simulated';
  static const _timeout = Duration(seconds: 45);

  // Memory only, for this app process (the web keeps them in sessionStorage).
  static HmrcTokens? _tokens;

  /// Forget the session (tests, and Disconnect).
  static void disconnect() => _tokens = null;

  bool get connected => _tokens != null;

  // --- OAuth (PKCE) ---------------------------------------------------------------------------------

  /// Start HMRC's consent page in the browser; in a demo, mark this session
  /// connected without any HMRC page.
  Future<void> startConnect() async {
    if (Demo.active) {
      _tokens = HmrcTokens(_demoToken, _demoToken, _now().add(const Duration(hours: 2)));
      return;
    }
    final rnd = Random.secure();
    final verifier = base64UrlNoPad(List<int>.generate(48, (_) => rnd.nextInt(256))); // 64 chars
    final challenge = base64UrlNoPad(sha256(ascii.encode(verifier)));
    final q = Uri(queryParameters: {'redirect_to': redirectTo, 'code_challenge': challenge}).query;
    final res = await _relay('GET', '/hmrc/authorize?$q') as Map<String, dynamic>;
    final url = res['url']?.toString();
    final state = res['state']?.toString();
    if (url == null || state == null) {
      throw RelayException('The relay did not return an HMRC sign-in address.', 0);
    }
    final prefs = await _prefs();
    // The verifier waits on this phone only until HMRC hands the code back (single use).
    await prefs.setString(_kPending, json.encode({'verifier': verifier, 'state': state}));
    if (!await _open(Uri.parse(url))) {
      await prefs.remove(_kPending);
      throw RelayException('Could not open the HMRC sign-in page.', 0);
    }
  }

  /// The result HMRC sent back to the app (`code` + `state`, or `error`),
  /// taken once from MainActivity; null when nothing arrived.
  Future<Map<String, String>?> takeCallback() async {
    String? raw;
    try {
      raw = await _channel.invokeMethod<String>('takeCallback');
    } catch (_) {
      return null;
    }
    if (raw == null || raw.isEmpty) return null;
    final uri = Uri.tryParse(raw);
    if (uri == null || uri.scheme != 'com.accnomos.app' || uri.host != 'hmrc') return null;
    final p = {...uri.queryParameters};
    if (p['state'] == null || (p['code'] == null && p['error'] == null)) return null;
    return p;
  }

  /// Swap the code for tokens with our verifier. The pending entry is single-use.
  Future<void> finishConnect(Map<String, String> cb) async {
    final prefs = await _prefs();
    final raw = prefs.getString(_kPending);
    await prefs.remove(_kPending);
    if (cb['error'] != null) {
      throw HmrcAuthException(
          "HMRC sign-in didn't finish: ${cb['error_description']?.isNotEmpty == true ? cb['error_description'] : cb['error']}");
    }
    if (raw == null) throw HmrcAuthException("This HMRC sign-in wasn't started on this phone. Connect again.");
    final pending = json.decode(raw) as Map<String, dynamic>;
    if (pending['state'] != cb['state']) {
      throw HmrcAuthException("HMRC sign-in state didn't match. Connect again.");
    }
    final t = await _relay('POST', '/hmrc/exchange', body: {
      'code': cb['code'],
      'state': cb['state'],
      'code_verifier': pending['verifier'],
    }) as Map<String, dynamic>;
    _save(t);
  }

  void _save(Map<String, dynamic> t) {
    final access = t['access_token']?.toString();
    final refresh = t['refresh_token']?.toString();
    if (access == null || refresh == null) throw HmrcAuthException('HMRC did not return a session. Connect again.');
    final secs = (t['expires_in'] as num?)?.toInt() ?? 3600;
    _tokens = HmrcTokens(access, refresh, _now().add(Duration(seconds: secs)));
  }

  /// A valid access token, refreshed through the relay a minute before it expires.
  Future<String> accessToken() async {
    final t = _tokens;
    if (t == null) throw HmrcAuthException('Not connected to HMRC.');
    if (_now().isBefore(t.expiresAt.subtract(const Duration(minutes: 1)))) return t.accessToken;
    try {
      _save(await _relay('POST', '/hmrc/refresh', body: {'refresh_token': t.refreshToken}) as Map<String, dynamic>);
      return _tokens!.accessToken;
    } catch (e) {
      _tokens = null;
      throw HmrcAuthException('Your HMRC session has ended ($e). Connect again.');
    }
  }

  // --- VAT (MTD) --------------------------------------------------------------------------------------

  Future<RelayResult> obligations(String vrn,
      {required String? accountId, required DateTime from, required DateTime to, String? scenario}) async {
    if (Demo.active) {
      return RelayResult(hmrc: {
        'obligations': [for (final o in demoObligations(to)) o.toJson()]
      });
    }
    return _vat('/vat/$vrn/obligations', accountId, {'from': isoDay(from), 'to': isoDay(to)}, scenario);
  }

  Future<RelayResult> submit(String vrn, Map<String, dynamic> returnBody,
      {required String? accountId, String? scenario}) async {
    if (Demo.active) {
      final net = (returnBody['netVatDue'] as num?) ?? 0;
      return RelayResult(hmrc: {
        'processingDate': _now().toUtc().toIso8601String(),
        'formBundleNumber': 'DEMO-000000000000',
        if (net > 0) 'paymentIndicator': 'DEMO (nothing to pay)',
      });
    }
    return _vat('/vat/$vrn/returns', accountId, {'return': returnBody}, scenario);
  }

  /// The facts this phone sends with every VAT call (also shown in tests).
  Future<Map<String, dynamic>> clientFacts(String? accountId) => _facts.collect(accountId: accountId);

  Future<RelayResult> _vat(String path, String? accountId, Map<String, dynamic> extra, String? scenario) async {
    final body = <String, dynamic>{
      'client_facts': await clientFacts(accountId),
      'method': connectionMethod,
      if (scenario != null && scenario.trim().isNotEmpty) 'gov_test_scenario': scenario.trim(),
      ...extra,
    };
    final res = await _relay('POST', path, body: body, token: await accessToken());
    return RelayResult.fromJson(res as Map<String, dynamic>);
  }

  Future<Object?> _relay(String method, String path, {Map<String, dynamic>? body, String? token}) async {
    if (Demo.active) throw RelayException("The demo sandbox doesn't contact HMRC.", 0);
    final req = http.Request(method, Uri.parse('$relayUrl$path'));
    if (body != null) {
      req.headers['Content-Type'] = 'application/json';
      req.body = json.encode(body);
    }
    if (token != null) req.headers['X-HMRC-Access-Token'] = token;
    http.StreamedResponse res;
    String text;
    try {
      res = await _client.send(req).timeout(_timeout);
      text = await res.stream.bytesToString();
    } catch (_) {
      throw RelayException("Couldn't reach the HMRC relay at $relayUrl.", 0);
    }
    Object? decoded;
    try {
      decoded = text.isEmpty ? null : json.decode(text);
    } catch (_) {
      decoded = null;
    }
    if (res.statusCode < 200 || res.statusCode >= 300) {
      final msg = errorMessage(decoded, 'HMRC relay $path answered ${res.statusCode}');
      if (res.statusCode == 401 && token != null) {
        _tokens = null;
        throw HmrcAuthException('HMRC refused the session ($msg). Connect again.');
      }
      throw RelayException(msg, res.statusCode);
    }
    return decoded;
  }

  // --- the VAT number to use ---------------------------------------------------------------------------

  Future<String> savedVrn(String? businessVat) async {
    if (Demo.active) return demoVrn;
    final prefs = await _prefs();
    final direct = prefs.getString(_kVrn);
    if (direct != null && direct.isNotEmpty) return direct;
    final digits = cleanVrn(businessVat ?? '');
    return RegExp(r'^\d{9}$').hasMatch(digits) ? digits : '';
  }

  Future<void> rememberVrn(String vrn) async {
    if (Demo.active) return;
    (await _prefs()).setString(_kVrn, vrn);
  }
}

String cleanVrn(String raw) => raw.replaceAll(RegExp(r'\s+'), '').toUpperCase().replaceFirst(RegExp('^GB'), '');

String isoDay(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// Relay / HMRC / FastAPI error text (the web's `errorMessage`).
String errorMessage(Object? body, String fallback) {
  if (body is Map) {
    final detail = body['detail'];
    if (detail is List) {
      return detail.map((d) => d is Map ? (d['msg'] ?? json.encode(d)).toString() : d.toString()).join('; ');
    }
    if (detail is String) return detail;
    final message = body['message'];
    if (message is String) {
      final errors = [
        for (final e in (body['errors'] as List?) ?? const [])
          if (e is Map && e['message'] != null) e['message'].toString(),
      ];
      return [message, ...errors].join(' · ');
    }
  }
  return fallback;
}

/// Calendar-quarter obligations for the year to [to] (stagger 1, as the sample
/// books use): the latest finished quarter and the current one open, the
/// earlier ones fulfilled — the web's `demoObligations`.
List<Obligation> demoObligations(DateTime to) {
  final out = <Obligation>[];
  final q = (to.month - 1) ~/ 3;
  for (var back = 4; back >= 0; back--) {
    final start = DateTime(to.year, (q - back) * 3 + 1, 1);
    final end = DateTime(start.year, start.month + 3, 0);
    final due = DateTime(end.year, end.month + 2, 7);
    final key = '${start.year.toString().substring(2)}A${(start.month - 1) ~/ 3 + 1}';
    final open = back <= 1;
    out.add(Obligation(
      periodKey: key,
      start: isoDay(start),
      end: isoDay(end),
      due: isoDay(due),
      status: open ? 'O' : 'F',
      received: open ? null : isoDay(due),
    ));
  }
  return out;
}

/// The runtime's `hmrc_body` (computed by code from the ledger) under the
/// obligation's period key, finalised: boxes 1–5 to the penny, 6–9 whole
/// pounds, box 5 as an absolute value (the web's `toReturnBody`).
Map<String, dynamic> toReturnBody(Map<String, dynamic> hmrcBody, String periodKey) {
  double p(String k) => ((num.tryParse('${hmrcBody[k] ?? 0}') ?? 0) * 100).round() / 100;
  int w(String k) => (num.tryParse('${hmrcBody[k] ?? 0}') ?? 0).truncate();
  return {
    'periodKey': periodKey,
    'vatDueSales': p('vatDueSales'),
    'vatDueAcquisitions': p('vatDueAcquisitions'),
    'totalVatDue': p('totalVatDue'),
    'vatReclaimedCurrPeriod': p('vatReclaimedCurrPeriod'),
    'netVatDue': p('netVatDue').abs(),
    'totalValueSalesExVAT': w('totalValueSalesExVAT'),
    'totalValuePurchasesExVAT': w('totalValuePurchasesExVAT'),
    'totalValueGoodsSuppliedExVAT': w('totalValueGoodsSuppliedExVAT'),
    'totalAcquisitionsExVAT': w('totalAcquisitionsExVAT'),
    'finalised': true,
  };
}
