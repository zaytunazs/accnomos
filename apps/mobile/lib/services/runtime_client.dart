import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart' show visibleForTesting;
import 'package:http/http.dart' as http;

import '../models/ask_answer.dart';
import '../models/calendar.dart';
import '../models/sample_books.dart';
import '../models/scan_job.dart';
import '../models/storage.dart';
import 'ai_route.dart';
import 'books_events.dart';
import 'demo.dart';
import 'settings.dart';

/// Error from the reader service. [message] is safe to show in the UI.
class RuntimeException implements Exception {
  RuntimeException(this.message);
  final String message;

  @override
  String toString() => message;
}

/// Books credentials for the `/books/*` endpoints. Header names mirror the
/// web's `runtimeHeaders()` in `apps/web/src/lib/runtime.ts` exactly.
class BooksAuth {
  BooksAuth({
    required this.graphToken,
    required this.accountKind,
    this.user,
    this.businessName,
  });

  /// Raw Graph access token, sent as-is like the web client does.
  final String graphToken;

  /// `personal` or `work`.
  final String accountKind;

  /// Signed-in user's email (the `X-User` header approvals need).
  final String? user;

  final String? businessName;
}

/// Talks to the Accnomos reader runtime. Covers every route in
/// services/runtime (the screens use a few of them so far).
class RuntimeClient {
  RuntimeClient(this.settings, {this.books, http.Client? httpClient})
      : _httpOverride = httpClient;
  final AppSettings settings;

  /// Present for every books call; null when nobody is signed in.
  final BooksAuth? books;

  /// Test transport, used instead of a fresh client for every call.
  final http.Client? _httpOverride;

  /// Transport for every call: the injected fake in tests, otherwise a new
  /// client each time (created at call time, so `http.runWithClient`
  /// zone mocks keep working as they did for the top-level functions).
  http.Client get _http => _httpOverride ?? http.Client();

  /// The saved VAT stagger as the runtime's query, like the web's
  /// `vatQuery()` in `apps/web/src/lib/vat-period.ts`: `start_month=` when
  /// the user kept a custom quarter start, else `stagger=`. Empty when
  /// nothing is saved — the runtime then assumes calendar quarters and
  /// says `assumed: true` instead of the app sending a default.
  @visibleForTesting
  Map<String, String> vatQuery() {
    final start = settings.vatStartMonth;
    if (start != null) return {'start_month': '$start'};
    final stagger = settings.vatStagger;
    if (stagger != null) return {'stagger': '$stagger'};
    return const {};
  }

  // Glimmer on a home machine takes 20–60 s per receipt; the runtime itself is fast.
  static const _timeout = Duration(seconds: 120);

  Map<String, String> get _headers {
    final demo = Demo.current;
    // Which AI answers first, only once the user has picked one.
    final route = clampAiRoute(settings.aiRoute);
    if (demo != null && books != null) {
      // A demo: the session id instead of a Graph token, and no X-AI-*
      // headers, so the runtime reads with its own Meta model chain, as the
      // website's demo does (this phone's own AI settings may point at a
      // machine on someone else's network).
      return {
        Demo.header: demo.session,
        'X-Account-Kind': 'personal',
        'X-User': demo.user,
        if (settings.autopilotLevel != 'L2') 'X-Autopilot': 'off',
        kAiRouteHeader: ?route,
      };
    }
    // 'auto': no AI choice is sent, so the runtime reads with its own Meta
    // model chain (the website's default). A local choice without an
    // address falls back to the same chain rather than a blank URL.
    final ownAi = settings.aiMode == 'key' ||
        (settings.aiMode == 'local' && settings.aiBaseUrl.trim().isNotEmpty);
    final headers = <String, String>{
      if (ownAi) ...{
        'X-AI-Mode': settings.aiMode,
        'X-AI-Base-Url': settings.aiBaseUrl,
        'X-AI-Model': settings.aiModel,
      },
      kAiRouteHeader: ?route,
    };
    // Autopilot posts only at level L2 (Settings > Automation, like the
    // web's runtime.ts): every other level sends `X-Autopilot: off`, so a
    // phone scan never posts without the user.
    if (settings.autopilotLevel != 'L2') {
      headers['X-Autopilot'] = 'off';
    }
    final key = settings.apiKey;
    if (settings.aiMode == 'key' && key != null && key.isNotEmpty) {
      headers['X-Meta-Api-Key'] = key;
    }
    final auth = books;
    if (auth != null) {
      headers['X-Graph-Token'] = auth.graphToken;
      headers['X-Account-Kind'] = auth.accountKind;
      final user = auth.user;
      if (user != null && user.isNotEmpty) headers['X-User'] = user;
      final business = auth.businessName;
      if (business != null && business.isNotEmpty) {
        headers['X-Business-Name'] = business;
      }
    }
    return headers;
  }

  /// The headers every runtime call carries (tests only).
  @visibleForTesting
  Map<String, String> get debugHeaders => _headers;

  void _requireBooks() {
    if (books == null) {
      throw RuntimeException('Sign in with Microsoft first.');
    }
  }

  /// The demo session id for this app run, for reading photos before
  /// sign-in (`/extract` needs a sign-in or a demo session). Memory only.
  static String? _demoSession;

  static const _signInToRead =
      'Sign in to read photos. This reader has no demo mode to read them '
      'without an account.';

  /// Forget the remembered demo session (tests only).
  @visibleForTesting
  static void forgetDemoSession() => _demoSession = null;

  /// A live demo session id, like the web's `startDemo()` in
  /// `apps/web/src/lib/demo.ts`: the remembered one while
  /// `GET /demo/session` still answers, else a new `POST /demo/session`.
  /// Throws a sign-in message when the reader has demo mode off.
  @visibleForTesting
  Future<String> demoSession() async {
    final client = _http;
    final base = settings.runtimeUrl;
    final known = _demoSession;
    if (known != null) {
      final alive = await client.get(Uri.parse('$base/demo/session'),
          headers: {'X-Demo-Session': known}).timeout(_timeout);
      if (alive.statusCode == 200) return known;
      _demoSession = null;
    }
    final res = await client
        .post(Uri.parse('$base/demo/session'))
        .timeout(_timeout);
    if (res.statusCode < 200 || res.statusCode >= 300) {
      if (res.statusCode == 401 || res.statusCode == 403) {
        throw RuntimeException(_signInToRead);
      }
      _fail(res.statusCode, res.body.trim());
    }
    final id = (json.decode(res.body) as Map<String, dynamic>)['session'];
    if (id is! String || id.isEmpty) {
      throw RuntimeException(_signInToRead);
    }
    return _demoSession = id;
  }

  /// Send [image] to the runtime and return the decoded JSON response.
  /// Signed in, the Graph token goes with it; before sign-in the call rides
  /// on a demo session (see [demoSession]).
  Future<Map<String, dynamic>> extract(File image) async {
    final uri = Uri.parse('${settings.runtimeUrl}/extract');
    try {
      final signedIn = books != null;
      final demo = signedIn ? null : await demoSession();
      final request = http.MultipartRequest('POST', uri)
        ..headers.addAll(_headers)
        ..files.add(await http.MultipartFile.fromPath('file', image.path));
      if (demo != null) request.headers['X-Demo-Session'] = demo;
      final streamed = await _http.send(request).timeout(_timeout);
      final body = await streamed.stream.bytesToString();
      if (!signedIn && streamed.statusCode == 401) {
        _demoSession = null; // ended or switched off: start over next time
        throw RuntimeException(_signInToRead);
      }
      if (streamed.statusCode < 200 || streamed.statusCode >= 300) {
        _fail(streamed.statusCode, body.trim());
      }
      return json.decode(body) as Map<String, dynamic>;
    } on TimeoutException {
      throw RuntimeException(
          'Reading took too long (over 20 s). Check the reader and try again.');
    } on SocketException {
      throw RuntimeException(
          'Could not reach the reader at ${settings.runtimeUrl}. '
          'Is it running?');
    } on RuntimeException {
      rethrow;
    } catch (e) {
      throw RuntimeException('Could not read that receipt. $e');
    }
  }

  /// The model the reader service's own chain answers with (its first
  /// configured provider in `GET /health` → `ai`), or null.
  static String? serverModel(Map<String, dynamic>? health) {
    final ai = health?['ai'];
    if (ai is! Map) return null;
    final providers = ai['providers'];
    if (providers is! List) return null;
    for (final p in providers) {
      if (p is Map && p['configured'] == true) {
        final model = (p['model'] ?? '').toString().trim();
        if (model.isNotEmpty) return model;
      }
    }
    return null;
  }

  /// Ask the runtime whether the configured AI answers. For 'auto' (the
  /// reader's own chain) `GET /health` says which Meta models are set up.
  Future<Map<String, dynamic>> aiTest() async {
    if (settings.aiMode != 'key' &&
        !(settings.aiMode == 'local' && settings.aiBaseUrl.trim().isNotEmpty)) {
      final health = await this.health();
      if (health == null) {
        throw RuntimeException(
            'Could not reach the reader at ${settings.runtimeUrl}. '
            'Is it running?');
      }
      final model = serverModel(health);
      return {
        'ok': model != null,
        'mode': 'auto',
        'model': model ?? '',
        'detail': model != null
            ? 'The reader service\'s Meta models answer'
            : 'The reader service has no AI set up',
      };
    }
    final uri = Uri.parse('${settings.runtimeUrl}/ai/test');
    try {
      final response = await _http.post(
            uri,
            headers: {..._headers, 'Content-Type': 'application/json'},
            body: json.encode({
              'mode': settings.aiMode,
              'base_url': settings.aiBaseUrl,
              'model': settings.aiModel,
            }),
          )
          .timeout(_timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        _fail(response.statusCode, response.body.trim());
      }
      final decoded = json.decode(response.body);
      if (decoded is Map<String, dynamic>) return decoded;
      return {'result': decoded.toString()};
    } on TimeoutException {
      throw RuntimeException(
          'The test took too long (over 20 s). Check the reader address.');
    } on SocketException {
      throw RuntimeException(
          'Could not reach the reader at ${settings.runtimeUrl}. '
          'Is it running?');
    } on RuntimeException {
      rethrow;
    } catch (e) {
      throw RuntimeException('Connection test failed. $e');
    }
  }

  /// Read the user's `00 Inbox` and propose entries.
  /// `POST /books/scan` → `{proposals, errors}`. The saved VAT settings
  /// set the period that scanned dates are checked against, like the web.
  Future<ScanOutcome> scan() async {
    _requireBooks();
    final uri = _uri('/books/scan');
    try {
      final response = await _http.post(
            uri,
            headers: {..._headers, 'Content-Type': 'application/json'},
          )
          .timeout(_timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        _fail(response.statusCode, response.body.trim());
      }
      final decoded = json.decode(response.body) as Map<String, dynamic>;
      final proposals = <Map<String, dynamic>>[];
      if (decoded['proposals'] is List) {
        for (final p in decoded['proposals'] as List) {
          if (p is Map) proposals.add(Map<String, dynamic>.from(p));
        }
      }
      final errors = <ScanFileError>[];
      if (decoded['errors'] is List) {
        for (final e in decoded['errors'] as List) {
          if (e is Map) {
            errors.add(ScanFileError.fromJson(Map<String, dynamic>.from(e)));
          }
        }
      }
      return ScanOutcome(proposals: proposals, errors: errors);
    } on TimeoutException {
      throw RuntimeException(
          'The scan took too long (over 20 s). Check the reader and try again.');
    } on SocketException {
      throw RuntimeException(
          'Could not reach the reader at ${settings.runtimeUrl}. '
          'Is it running?');
    } on RuntimeException {
      rethrow;
    } catch (e) {
      throw RuntimeException('The scan failed. $e');
    }
  }

  /// Start reading 00 Inbox files in the background (`POST
  /// /books/scan/jobs`, `services/runtime/app/scan_jobs.py`): answers at
  /// once with the job; poll [scanJob] for progress. `names` null = every
  /// file in 00 Inbox. Nothing waits on the AI, so the 20 s scan timeout of
  /// the old blocking scan can no longer cut a slow read short.
  Future<ScanJob> startScanJob(
      {List<String>? names, String source = 'phone'}) async {
    final job = await _map('POST', '/books/scan/jobs',
        query: vatQuery(),
        body: {'names': ?names, 'source': source},
        what: 'start reading your Inbox');
    return ScanJob.fromJson(job);
  }

  /// One background scan. `GET /books/scan/jobs/{id}`.
  Future<ScanJob> scanJob(String id) async => ScanJob.fromJson(await _map(
      'GET', '/books/scan/jobs/${_seg(id)}',
      what: 'see how the reading is going'));

  /// The user's types for files waiting on them (`POST
  /// /books/scan/jobs/{id}/confirm`); reading them in full starts then.
  Future<ScanJob> confirmScanJob(String id, Map<String, String> kinds) async {
    final job = await _map('POST', '/books/scan/jobs/${_seg(id)}/confirm',
        query: vatQuery(),
        body: {
          'files': [
            for (final e in kinds.entries) {'name': e.key, 'kind': e.value},
          ],
        },
        what: 'confirm the document types');
    return ScanJob.fromJson(job);
  }

  /// Live proposals. `GET /books/proposals`.
  Future<List<Map<String, dynamic>>> proposals({String? status}) async {
    _requireBooks();
    final query = status == null ? '' : '?status=$status';
    final uri = Uri.parse('${settings.runtimeUrl}/books/proposals$query');
    try {
      final response =
          await _http.get(uri, headers: _headers).timeout(_timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        _fail(response.statusCode, response.body.trim());
      }
      final decoded = json.decode(response.body);
      if (decoded is List) {
        return [
          for (final p in decoded)
            if (p is Map) Map<String, dynamic>.from(p),
        ];
      }
      return const [];
    } on TimeoutException {
      throw RuntimeException(
          'Loading proposals took too long. Check the reader and try again.');
    } on SocketException {
      throw RuntimeException(
          'Could not reach the reader at ${settings.runtimeUrl}. '
          'Is it running?');
    } on RuntimeException {
      rethrow;
    } catch (e) {
      throw RuntimeException('Could not load proposals. $e');
    }
  }

  /// Approve a proposal. `POST /books/proposals/{id}/approve`.
  Future<Map<String, dynamic>> approve(
    String id, {
    Map<String, dynamic>? edits,
    bool always = false,
  }) async {
    _requireBooks();
    final uri =
        Uri.parse('${settings.runtimeUrl}/books/proposals/$id/approve');
    try {
      final response = await _http.post(
            uri,
            headers: {..._headers, 'Content-Type': 'application/json'},
            body: json.encode({'edits': edits, 'always': always}),
          )
          .timeout(_timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        _fail(response.statusCode, response.body.trim());
      }
      return json.decode(response.body) as Map<String, dynamic>;
    } on SocketException {
      throw RuntimeException(
          'Could not reach the reader at ${settings.runtimeUrl}. '
          'Is it running?');
    } on RuntimeException {
      rethrow;
    } catch (e) {
      throw RuntimeException('Approval failed. $e');
    }
  }

  /// Reject a proposal. `POST /books/proposals/{id}/reject`.
  Future<Map<String, dynamic>> reject(String id, {String reason = ''}) async {
    _requireBooks();
    final uri =
        Uri.parse('${settings.runtimeUrl}/books/proposals/$id/reject');
    try {
      final response = await _http.post(
            uri,
            headers: {..._headers, 'Content-Type': 'application/json'},
            body: json.encode({'reason': reason}),
          )
          .timeout(_timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        _fail(response.statusCode, response.body.trim());
      }
      return json.decode(response.body) as Map<String, dynamic>;
    } on SocketException {
      throw RuntimeException(
          'Could not reach the reader at ${settings.runtimeUrl}. '
          'Is it running?');
    } on RuntimeException {
      rethrow;
    } catch (e) {
      throw RuntimeException('Rejection failed. $e');
    }
  }

  /// Totals for the Home/Review screens. `GET /books/summary`.
  Future<Map<String, dynamic>> summary() async {
    _requireBooks();
    final uri = Uri.parse('${settings.runtimeUrl}/books/summary');
    try {
      final response =
          await _http.get(uri, headers: _headers).timeout(_timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        _fail(response.statusCode, response.body.trim());
      }
      return json.decode(response.body) as Map<String, dynamic>;
    } on SocketException {
      throw RuntimeException(
          'Could not reach the reader at ${settings.runtimeUrl}. '
          'Is it running?');
    } on RuntimeException {
      rethrow;
    } catch (e) {
      throw RuntimeException('Could not load the summary. $e');
    }
  }

  /// Home's other cards and the checked summary. `GET /books/home`, as the
  /// web's Home (services/runtime/app/home_overview.py).
  /// `summaryAi: false` asks for code's own summary (fast, no model call);
  /// Home shows that first and then swaps in the AI's words.
  Future<Map<String, dynamic>> home({String? today, bool summaryAi = true}) async {
    _requireBooks();
    final uri = _uri('/books/home',
        {'today': ?today, if (!summaryAi) 'summary_ai': 'false'});
    try {
      final response =
          await _http.get(uri, headers: _headers).timeout(_timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        _fail(response.statusCode, response.body.trim());
      }
      return json.decode(response.body) as Map<String, dynamic>;
    } on SocketException {
      throw RuntimeException(
          'Could not reach the reader at ${settings.runtimeUrl}. '
          'Is it running?');
    } on RuntimeException {
      rethrow;
    } catch (e) {
      throw RuntimeException('Could not load the summary. $e');
    }
  }

  /// The Home tiles in one call. `GET /books/dashboard`, with the saved VAT
  /// period, like the web's `vatQuery()`.
  /// [today] is `YYYY-MM-DD` on the phone, so the deadline counts from the
  /// user's day.
  Future<Map<String, dynamic>> dashboard({String? today}) async {
    _requireBooks();
    final uri = _uri('/books/dashboard', {'today': ?today});
    try {
      final response =
          await _http.get(uri, headers: _headers).timeout(_timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        _fail(response.statusCode, response.body.trim());
      }
      return json.decode(response.body) as Map<String, dynamic>;
    } on SocketException {
      throw RuntimeException(
          'Could not reach the reader at ${settings.runtimeUrl}. '
          'Is it running?');
    } on RuntimeException {
      rethrow;
    } catch (e) {
      throw RuntimeException('Could not load your figures. $e');
    }
  }

  /// The 9 VAT boxes for [period] ("2026-Q3", from [vatPeriods]), or for the
  /// current period when null. `GET /books/vat`, with the saved VAT period.
  Future<Map<String, dynamic>> vat({String? period}) {
    _requireBooks();
    return _map('GET', '/books/vat',
        query: {...vatQuery(), 'period': ?period},
        what: 'load the VAT return');
  }

  /// The current VAT period and the 8 before it, with status, newest first.
  /// `GET /books/vat/periods`, with the saved VAT period.
  Future<Map<String, dynamic>> vatPeriods() {
    _requireBooks();
    return _map('GET', '/books/vat/periods',
        query: vatQuery(), what: 'load VAT periods');
  }

  /// Hand HMRC's obligations to the runtime (it holds no HMRC token) so the
  /// period list marks fulfilled periods submitted. `POST /books/vat/obligations`.
  Future<Map<String, dynamic>> postVatObligations(
      List<Map<String, dynamic>> obligations) {
    _requireBooks();
    return _map('POST', '/books/vat/obligations',
        body: {'obligations': obligations}, what: "store HMRC's VAT periods");
  }

  /// Ask the books a question. `POST /books/ask` → a checked [AskAnswer].
  /// [periodStart]/[periodEnd] are `YYYY-MM-DD`; omit both for the current
  /// VAT quarter (the saved VAT period rides along as the query, so the
  /// runtime knows which quarter that is). Only the last six [history]
  /// turns are sent.
  Future<AskAnswer> ask(
    String question, {
    String? periodStart,
    String? periodEnd,
    List<AskTurn> history = const [],
  }) async {
    _requireBooks();
    final uri = _uri('/books/ask');
    final recent =
        history.length > 6 ? history.sublist(history.length - 6) : history;
    try {
      final response = await _http.post(
            uri,
            headers: {..._headers, 'Content-Type': 'application/json'},
            body: json.encode({
              'question': question,
              'period': periodStart != null && periodEnd != null
                  ? {'start': periodStart, 'end': periodEnd}
                  : null,
              'history': [for (final t in recent) t.toJson()],
            }),
          )
          .timeout(_timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        _fail(response.statusCode, response.body.trim());
      }
      return AskAnswer.fromJson(
          json.decode(response.body) as Map<String, dynamic>);
    } on TimeoutException {
      throw RuntimeException(
          'Answering took too long. Check your AI and try again.');
    } on SocketException {
      throw RuntimeException(
          'Could not reach the reader at ${settings.runtimeUrl}. '
          'Is it running?');
    } on RuntimeException {
      rethrow;
    } catch (e) {
      throw RuntimeException('Could not get an answer. $e');
    }
  }

  /// `POST /actions/approve`: runs the proposal once and returns the result's
  /// markdown summary (e.g. "Logged 7.5 hours for Sam on Elm Road.").
  ///
  /// [heard]: approved by a spoken yes (the assistant's "Shall I go ahead?"):
  /// sent as `via: "voice"` with what was heard; the runtime checks the words
  /// again, refuses a card that sends or moves money, and audits both.
  Future<String> approveAction(ProposedAction action, {String? heard}) =>
      _action('approve', action, 'Could not approve that', heard: heard);

  /// `POST /actions/reject`: nothing happens except a line in the audit log.
  Future<String> rejectAction(ProposedAction action) =>
      _action('reject', action, 'Could not reject that');

  Future<String> _action(
    String verb,
    ProposedAction action,
    String what, {
    String? heard,
  }) async {
    _requireBooks();
    final uri = Uri.parse('${settings.runtimeUrl}/actions/$verb');
    try {
      final response = await _http.post(
            uri,
            headers: {..._headers, 'Content-Type': 'application/json'},
            body: json.encode({
              'action': action.raw,
              if (heard != null) 'via': 'voice',
              if (heard != null)
                'heard': heard.length > 300 ? heard.substring(0, 300) : heard,
            }),
          )
          .timeout(_timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        String? detail;
        try {
          detail = (json.decode(response.body) as Map)['detail']?.toString();
        } catch (_) {
          detail = null;
        }
        if (detail != null) throw RuntimeException(detail);
        _fail(response.statusCode, response.body.trim());
      }
      final body = json.decode(response.body) as Map<String, dynamic>;
      return (body['summary_md'] ?? 'Rejected. Nothing was done.').toString();
    } on TimeoutException {
      throw RuntimeException('$what: the reader took too long.');
    } on SocketException {
      throw RuntimeException(
          'Could not reach the reader at ${settings.runtimeUrl}. '
          'Is it running?');
    } on RuntimeException {
      rethrow;
    } catch (e) {
      throw RuntimeException('$what. $e');
    }
  }

  /// Send a WAV recording and get back the transcript plus the checked
  /// answer. `POST /books/ask/voice` (multipart field `audio`) →
  /// `{transcript, answer?}` — `answer`, when present, has the same shape
  /// as `POST /books/ask`.
  ///
  /// Throws [RuntimeException] carrying the server's message when the
  /// runtime cannot transcribe (400/503 in local mode or without ffmpeg).
  /// Callers fall back to typing in that case.
  Future<VoiceAnswer> askVoice(
    List<int> wavBytes, {
    String filename = 'question.wav',
    List<AskTurn> history = const [],
  }) async {
    _requireBooks();
    final uri = _uri('/books/ask/voice');
    final recent =
        history.length > 6 ? history.sublist(history.length - 6) : history;
    try {
      final request = http.MultipartRequest('POST', uri)
        ..headers.addAll(_headers)
        ..files.add(http.MultipartFile.fromBytes(
          'audio',
          wavBytes,
          filename: filename,
        ));
      // Earlier turns, so a spoken follow-up ("and last month?") is understood.
      if (recent.isNotEmpty) {
        request.fields['history'] =
            json.encode([for (final t in recent) t.toJson()]);
      }
      final streamed = await _http.send(request).timeout(_timeout);
      final body = await streamed.stream.bytesToString();
      if (streamed.statusCode < 200 || streamed.statusCode >= 300) {
        _fail(streamed.statusCode, body.trim());
      }
      return VoiceAnswer.fromJson(
          json.decode(body) as Map<String, dynamic>);
    } on TimeoutException {
      throw RuntimeException(
          'Listening took too long. Check the reader and try again.');
    } on SocketException {
      throw RuntimeException(
          'Could not reach the reader at ${settings.runtimeUrl}. '
          'Is it running?');
    } on RuntimeException {
      rethrow;
    } catch (e) {
      throw RuntimeException('Could not handle that recording. $e');
    }
  }

  /// Posted proposals decided by Autopilot (`decided_by == 'autopilot'`).
  /// `GET /books/proposals?status=posted`, filtered client-side.
  Future<List<AutopilotApproval>> autopilotApprovals() async {
    final raw = await proposals(status: 'posted');
    return AutopilotApproval.fromProposals(raw);
  }

  /// Whether this reader exposes `POST /books/undo/{event_id}`, checked
  /// against its OpenAPI schema. False when offline or on runtimes that
  /// predate the undo route (no such route in `routes_books.py` on main).
  Future<bool> supportsUndo() async {
    final uri = Uri.parse('${settings.runtimeUrl}/openapi.json');
    try {
      final response = await _http.get(uri, headers: _headers)
          .timeout(const Duration(seconds: 10));
      if (response.statusCode != 200) return false;
      final decoded = json.decode(response.body);
      if (decoded is Map && decoded['paths'] is Map) {
        for (final key in (decoded['paths'] as Map).keys) {
          if (key.toString().contains('/books/undo/')) return true;
        }
      }
      return false;
    } catch (_) {
      return false;
    }
  }

  /// Reverse an Autopilot approval. `POST /books/undo/{event_id}`.
  /// Throws [RuntimeException]; callers treat status 404 as "this reader
  /// does not expose undo" and hide the Autopilot section.
  Future<Map<String, dynamic>> undoEvent(String eventId) async {
    _requireBooks();
    final uri =
        Uri.parse('${settings.runtimeUrl}/books/undo/$eventId');
    try {
      final response = await _http.post(
            uri,
            headers: {..._headers, 'Content-Type': 'application/json'},
          )
          .timeout(_timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        _fail(response.statusCode, response.body.trim());
      }
      final decoded = json.decode(response.body);
      if (decoded is Map<String, dynamic>) return decoded;
      return {'result': decoded.toString()};
    } on SocketException {
      throw RuntimeException(
          'Could not reach the reader at ${settings.runtimeUrl}. '
          'Is it running?');
    } on RuntimeException {
      rethrow;
    } catch (e) {
      throw RuntimeException('Undo failed. $e');
    }
  }

  // ------------------------------------------------------------------ //
  // The rest of the runtime's routes, one thin call each. Same paths and
  // bodies as `runtime` in apps/web/src/lib/runtime.ts. Money is integer
  // pence; dates are `YYYY-MM-DD`.
  // ------------------------------------------------------------------ //

  /// `GET /health` (no sign-in needed); null when the reader does not answer.
  Future<Map<String, dynamic>?> health() async {
    try {
      final response = await _http.get(Uri.parse('${settings.runtimeUrl}/health'))
          .timeout(const Duration(seconds: 10));
      if (response.statusCode != 200) return null;
      final decoded = json.decode(response.body);
      return decoded is Map ? Map<String, dynamic>.from(decoded) : null;
    } catch (_) {
      return null;
    }
  }

  /// `GET /books/proposals/{id}`.
  Future<Map<String, dynamic>> proposal(String id) =>
      _map('GET', '/books/proposals/${_seg(id)}', what: 'load that proposal');

  /// `POST /books/undo/{eventId}`: a reversing entry; the proposal goes back
  /// to Review. Returns `{reversal, proposal}`.
  Future<Map<String, dynamic>> undo(String eventId) =>
      _map('POST', '/books/undo/${_seg(eventId)}', what: 'undo that entry');

  /// Autopilot rules. `GET /books/rules`.
  Future<List<Map<String, dynamic>>> rules() =>
      _list('GET', '/books/rules', what: 'load Autopilot rules');

  /// `DELETE /books/rules/{supplierKey}`.
  Future<Map<String, dynamic>> removeRule(String supplierKey) => _map(
      'DELETE', '/books/rules/${_seg(supplierKey)}',
      what: 'remove that rule');

  /// `POST /books/rebuild`: regenerate Books.xlsx now.
  Future<Map<String, dynamic>> rebuild() =>
      _map('POST', '/books/rebuild', what: 'rebuild Books.xlsx');

  /// `GET /books/deadlines`, with the saved VAT period, like the web.
  /// [months] is 3 (quarterly) or 1 (monthly); [today] is `YYYY-MM-DD`.
  Future<Map<String, dynamic>> deadlines({int months = 3, String? today}) {
    return _map('GET', '/books/deadlines',
        query: {
          ...vatQuery(),
          'months': '$months',
          'today': ?today,
        },
        what: 'load VAT deadlines');
  }

  /// [path] with the saved VAT query appended (`?stagger=2`, or nothing
  /// when nothing is saved), plus [extra] parameters. Like the web's
  /// `withQuery` in `apps/web/src/lib/runtime.ts`.
  Uri _uri(String path, [Map<String, String>? extra]) {
    final query = {...vatQuery(), ...?extra};
    var uri = Uri.parse('${settings.runtimeUrl}$path');
    if (query.isNotEmpty) uri = uri.replace(queryParameters: query);
    return uri;
  }

  /// The audit trail, newest first. `GET /audit` → `{start, end, entries,
  /// truncated}`; each entry `{ts, actor, actor_kind, actor_label, event,
  /// summary, refs}`. Reads only. [actor] is `user`, `agent`, an agent
  /// name such as `autopilot`, or a full actor; [kind] an event such as
  /// `approved` or a family such as `invoice` — the same filters the web's
  /// audit page sends.
  Future<Map<String, dynamic>> audit(
          {String? from,
          String? to,
          String? actor,
          String? kind,
          int limit = 200}) =>
      _map('GET', '/audit',
          query: {
            'from': ?from,
            'to': ?to,
            'actor': ?actor,
            'kind': ?kind,
            'limit': '$limit',
          },
          what: 'load the audit trail');

  /// `GET /close`: the month that ended last (and any closed month changed
  /// since), for Home. Reads only. [today] is `YYYY-MM-DD`.
  Future<Map<String, dynamic>> closeOverview({String? today}) =>
      _map('GET', '/close',
          query: {'today': ?today}, what: 'load the month-end status');

  /// `GET /close/{yyyy-mm}`: the month's status, its last run (the nine
  /// steps), the close records and changes since. Reads only: the phone
  /// shows the checklist; the close is run on the web.
  Future<Map<String, dynamic>> closeMonth(String month, {String? today}) =>
      _map('GET', '/close/${_seg(month)}',
          query: {'today': ?today}, what: 'load the month-end checklist');

  /// `POST /books/export`: everything as one zip in `07 Reports/Exports`
  /// (a second run the same day is kept beside the first). Posts nothing.
  /// Same call as the web's Settings › Your data button.
  Future<Map<String, dynamic>> booksExport() => _map('POST', '/books/export',
      what: 'export your data');

  /// `GET /files/overview`: files and sizes per folder and per tax year, the
  /// largest documents and duplicate sets. Reads only (the Files page on the
  /// web moves, archives and cleans up; the phone shows the totals).
  Future<StorageOverview> storageOverview() async => StorageOverview.fromJson(
      await _map('GET', '/files/overview', what: 'add up your storage'));

  /// `POST /backups`: Back up now, a dated zip of _System in Backups/ with a
  /// manifest and a .sha256 beside it; older ones beyond the kept number go
  /// to _Trash. Returns `{backup: {path, name, size, files, ...}, retired}`.
  Future<Map<String, dynamic>> backUpNow() =>
      _map('POST', '/backups', what: 'back up your books');

  /// `GET /books/sample`: how far loading the sample books has got (state
  /// `none` with `empty` when never started here).
  Future<SampleStatus> sampleBooksStatus() => _sample('GET', '/books/sample');

  /// `POST /books/sample` starts loading the sample books into an empty
  /// folder; with [carryOn] it is `POST /books/sample/continue`, which hands
  /// the running job this request's fresh Graph token. A 409/429/503 with
  /// the runtime's sentence throws [SampleNote].
  Future<SampleStatus> loadSampleBooks({bool carryOn = false}) =>
      _sample('POST', carryOn ? '/books/sample/continue' : '/books/sample');

  Future<SampleStatus> _sample(String method, String path) async {
    _requireBooks();
    final request = http.Request(method, Uri.parse('${settings.runtimeUrl}$path'))
      ..headers.addAll(_headers);
    try {
      final streamed = await _http.send(request).timeout(_timeout);
      final text = await streamed.stream.bytesToString();
      final code = streamed.statusCode;
      if (code == 409 || code == 429 || code == 503) {
        final sentence = _detail(text);
        if (sentence != null) throw SampleNote(sentence);
      }
      if (code < 200 || code >= 300) _fail(code, text.trim());
      final decoded = text.isEmpty ? null : json.decode(text);
      return SampleStatus.fromJson(
          decoded is Map ? Map<String, dynamic>.from(decoded) : {});
    } on TimeoutException {
      throw RuntimeException(
          'Could not load sample books: the reader took too long. Try again.');
    } on SocketException {
      throw RuntimeException(
          'Could not reach the reader at ${settings.runtimeUrl}. '
          'Is it running?');
    } on SampleNote {
      rethrow;
    } on RuntimeException {
      rethrow;
    } catch (e) {
      throw RuntimeException('Could not load sample books. $e');
    }
  }

  /// FastAPI's `{"detail": "sentence"}`; null when there is no sentence.
  static String? _detail(String body) {
    try {
      final decoded = json.decode(body);
      final detail = decoded is Map ? decoded['detail'] : null;
      return detail is String && detail.trim().isNotEmpty
          ? detail.trim()
          : null;
    } catch (_) {
      return null;
    }
  }

  /// To-dos in `_System/Todos/todos.json`. `GET /todos`, soonest first.
  Future<List<Map<String, dynamic>>> todos() =>
      _list('GET', '/todos', what: 'load to-dos');

  /// `GET /accountant`: who your books are shared with (accountants and
  /// the Accnomos accountants opt-in), from `_System/accountant.json`.
  /// Read-only on the phone; inviting and removing happen on the web.
  Future<Map<String, dynamic>> accountant() =>
      _map('GET', '/accountant', what: 'load your accountant');

  /// `GET /queries`: your accountant's queries and the answers, newest
  /// activity first (`_System/queries/`). Read-only on the phone.
  Future<List<Map<String, dynamic>>> queries({String? status}) => _list(
      'GET', '/queries',
      query: {'status': ?status}, what: 'load queries');

  /// `POST /todos`: add one line of text. Returns the saved to-do.
  Future<Map<String, dynamic>> addTodo(String text) => _map('POST', '/todos',
      body: {'text': text}, what: 'add that to-do');

  /// `DELETE /todos/{id}`: tick one off.
  Future<Map<String, dynamic>> deleteTodo(String id) =>
      _map('DELETE', '/todos/${_seg(id)}', what: 'tick off that to-do');

  /// `POST /mail/triage`: the last days of business mail with summaries,
  /// suggested replies and to-dos. Needs `Mail.Read` on the Graph token;
  /// without AI headers the summaries are written by code. Changes nothing.
  Future<Map<String, dynamic>> mailTriage(
          {int sinceDays = 7, int maxThreads = 20}) =>
      _map('POST', '/mail/triage',
          body: {'since_days': sinceDays, 'max_threads': maxThreads},
          what: 'check the inbox');

  /// `POST /mail/draft-reply`: save an edited reply as an Outlook draft.
  /// Needs `Mail.ReadWrite` and `X-User`. Never sends.
  Future<Map<String, dynamic>> draftReply(String messageId, String body) =>
      _map('POST', '/mail/draft-reply',
          body: {'message_id': messageId, 'body': body},
          what: 'save that draft');

  /// `POST /mail/scan`. The Graph token must carry `Mail.Read`.
  /// `GET /mail/mailboxes`: the mailboxes Outlook intake reads, the signed-in
  /// one first (addresses, folder, sender lists, last check; never tokens).
  /// Linked on the web only: their sign-ins live in the browser.
  Future<List<Map<String, dynamic>>> mailboxes() async {
    final result =
        await _map('GET', '/mail/mailboxes', what: 'load your mailboxes');
    final list = result['mailboxes'];
    if (list is! List) return [];
    return [
      for (final m in list)
        if (m is Map) Map<String, dynamic>.from(m),
    ];
  }

  Future<Map<String, dynamic>> mailScan(
          {int sinceDays = 14, bool dryRun = false}) =>
      _map('POST', '/mail/scan',
          body: {'since_days': sinceDays, 'dry_run': dryRun},
          what: 'check the inbox');

  /// `POST /plan/day`: proposes a day and writes nothing. Same path and body
  /// as the web's `planDay` in `apps/web/src/lib/runtime.ts`. The caller
  /// passes a calendar-scoped token via [graphToken]: `Calendars.Read` is
  /// asked for the first time the user plans a day — never at sign-in.
  Future<Map<String, dynamic>> planDay({
    required String date,
    Map<String, dynamic>? constraints,
    List<String> jobIds = const [],
    String? graphToken,
  }) {
    final body = <String, Object?>{
      'date': date,
      'constraints': ?constraints,
      if (jobIds.isNotEmpty) 'job_ids': jobIds,
    };
    return _mapWithToken('POST', '/plan/day',
        body: body, what: 'plan that day', graphToken: graphToken);
  }

  /// `POST /plan/day/apply`: the plan's new items become calendar events.
  /// Call only from the Apply confirmation: [graphToken] carries
  /// `Calendars.ReadWrite`, asked for only now. Same path and body as the
  /// web's `applyPlan`.
  Future<Map<String, dynamic>> applyPlan({
    required String date,
    required List<Map<String, dynamic>> plan,
    String? graphToken,
  }) =>
      _mapWithToken('POST', '/plan/day/apply',
          body: {'date': date, 'plan': plan},
          what: 'add that plan to your calendar',
          graphToken: graphToken);

  /// One books call with an optional calendar-scoped [graphToken] instead of
  /// the sign-in token (day planning asks for calendar scopes only when used).
  Future<Map<String, dynamic>> _mapWithToken(
    String method,
    String path, {
    Object? body,
    Map<String, String> query = const {},
    required String what,
    String? graphToken,
  }) async {
    if (graphToken != null) {
      final saved = books;
      final client = RuntimeClient(
        settings,
        books: BooksAuth(
          graphToken: graphToken,
          accountKind: saved?.accountKind ?? 'personal',
          user: saved?.user,
          businessName: saved?.businessName,
        ),
      );
      return client._map(method, path, body: body, query: query, what: what);
    }
    return _map(method, path, body: body, query: query, what: what);
  }

  // Calendar (/calendar/*), the same routes and bodies as the web's runtime.ts.
  // Reading and writing events needs a calendar-scoped token (Calendars.ReadWrite,
  // asked for when the user first opens Calendar or taps "Add to calendar"):
  // build the client with it. In a demo it is the session's own calendar.

  /// `GET /calendar/events`: events overlapping [start]..[end] (`YYYY-MM-DD`,
  /// at most 62 days), Europe/London times.
  Future<List<CalendarEvent>> calendarEvents({String? start, String? end}) async =>
      CalendarEvent.listFromJson(await _json('GET', '/calendar/events',
          query: {'start': ?start, 'end': ?end}, what: 'load your calendar'));

  /// `POST /calendar/events` with `check_only`: the events it would clash
  /// with; writes nothing.
  Future<List<CalendarClash>> checkCalendarEvent(Map<String, Object?> event) async {
    final json = await _map('POST', '/calendar/events',
        body: {...event, 'check_only': true}, what: 'check your calendar');
    return CalendarClash.listFromJson(json['conflicts']);
  }

  /// `POST /calendar/events`: add one. Without [allowConflict] a clash is
  /// refused (409); pass it after the user said "Add anyway".
  Future<CalendarEvent> addCalendarEvent(Map<String, Object?> event,
          {bool allowConflict = false}) async =>
      CalendarEvent.fromJson(await _map('POST', '/calendar/events',
          body: {...event, if (allowConflict) 'allow_conflict': true},
          what: 'add that to your calendar'));

  /// `DELETE /calendar/events/{id}` with `{"confirm": true}`.
  Future<void> removeCalendarEvent(String id) async {
    await _json('DELETE', '/calendar/events/${_seg(id)}',
        body: {'confirm': true}, what: 'remove that from your calendar');
  }

  /// `GET /calendar/conflicts`: pairs of events already in the calendar that clash.
  Future<List<CalendarClashPair>> calendarConflicts({String? start, String? end}) async =>
      CalendarClashPair.listFromJson(await _json('GET', '/calendar/conflicts',
          query: {'start': ?start, 'end': ?end}, what: 'check your calendar'));

  /// `POST /calendar/deadlines/sync` (with the saved VAT period). With
  /// [keys], only those deadlines (the per-deadline "Add to calendar").
  Future<DeadlineSyncResult> syncDeadlines({List<String>? keys}) async =>
      DeadlineSyncResult.fromJson(await _map('POST', '/calendar/deadlines/sync',
          query: vatQuery(),
          body: {'confirm': true, 'keys': ?keys},
          what: 'add your deadlines to your calendar'));

  /// `GET /calendar/deadlines`: what a sync would add and which are in the
  /// calendar already. Reads no calendar, so the sign-in token is enough.
  Future<CalendarDeadlines> calendarDeadlines() async =>
      CalendarDeadlines.fromJson(await _map('GET', '/calendar/deadlines',
          query: vatQuery(), what: 'load your deadlines'));

  /// `GET /calendar/deadlines/status`.
  Future<DeadlineSyncStatus> deadlinesStatus() async => DeadlineSyncStatus.fromJson(
      await _map('GET', '/calendar/deadlines/status', what: 'load your calendar settings'));

  /// `PUT /calendar/deadlines/preference`: "Add all deadlines to my calendar automatically".
  Future<DeadlineSyncStatus> setDeadlinesKeep(bool keep) async => DeadlineSyncStatus.fromJson(
      await _map('PUT', '/calendar/deadlines/preference',
          body: {'keep': keep}, what: 'save that setting'));

  // Bank statements (/books/bank/*).

  /// `POST /books/bank/import`: the same file twice changes nothing.
  Future<Map<String, dynamic>> bankImport(File csv) =>
      _upload('/books/bank/import', 'file', csv,
          what: 'import that statement');

  Future<List<Map<String, dynamic>>> bankStatements() =>
      _list('GET', '/books/bank/statements', what: 'load bank statements');

  /// [status]: unmatched, matched, suggested, transfer or ignored.
  /// `GET /books/bank/lines`. [open] true: only the open lines, by the one
  /// definition the summary and Home use (business: not yet matched;
  /// household: no category). Personal books' lines carry
  /// `household_category`, `household_source` and `household_sorted`.
  Future<List<Map<String, dynamic>>> bankLines({String? status, bool? open}) =>
      _list('GET', '/books/bank/lines',
          query: {'status': ?status, if (open != null) 'open': '$open'},
          what: 'load bank lines');

  Future<List<Map<String, dynamic>>> bankSuggestions() =>
      _list('GET', '/books/bank/suggestions', what: 'load suggested matches');

  Future<List<Map<String, dynamic>>> bankUnmatched() =>
      _list('GET', '/books/bank/unmatched', what: 'load unmatched lines');

  Future<Map<String, dynamic>> bankSummary() =>
      _map('GET', '/books/bank/summary', what: 'load the bank summary');

  Future<Map<String, dynamic>> bankMatch(String lineId, List<String> eventIds) =>
      _map('POST', '/books/bank/lines/${_seg(lineId)}/match',
          body: {'event_ids': eventIds}, what: 'confirm that match');

  /// Reopen a matched, transfer or ignored line.
  Future<Map<String, dynamic>> bankUnmatch(String lineId) => _map(
      'POST', '/books/bank/lines/${_seg(lineId)}/unmatch',
      what: 'reopen that line');

  Future<Map<String, dynamic>> bankTransfer(String lineId) => _map(
      'POST', '/books/bank/lines/${_seg(lineId)}/transfer',
      what: 'mark that line as a transfer');

  Future<Map<String, dynamic>> bankIgnore(String lineId) => _map(
      'POST', '/books/bank/lines/${_seg(lineId)}/ignore',
      what: 'ignore that line');

  /// An expense proposal (no VAT claimed) that waits in Review.
  Future<Map<String, dynamic>> bankExpenseProposal(String lineId) => _map(
      'POST', '/books/bank/lines/${_seg(lineId)}/expense-proposal',
      what: 'propose that expense');

  /// Bank rules in evaluation order (first match wins).
  /// `GET /books/bank/rules`.
  Future<List<Map<String, dynamic>>> bankRules() =>
      _list('GET', '/books/bank/rules', what: 'load bank rules');

  /// `POST /books/bank/rules` (201): "when the description contains X,
  /// code it to Y". [rule] keeps the runtime's shape: `{name, match: {op,
  /// value}, amount_min_pence?, amount_max_pence?, direction, action:
  /// {account, vat_code?, contact?, job_id?}}` — the same body the web's
  /// `BankRules` form sends.
  Future<Map<String, dynamic>> createBankRule(Map<String, dynamic> rule) =>
      _map('POST', '/books/bank/rules',
          body: rule, what: 'save that rule');

  /// `PUT /books/bank/rules/{id}`: same body as [createBankRule].
  Future<Map<String, dynamic>> updateBankRule(
          String id, Map<String, dynamic> rule) =>
      _map('PUT', '/books/bank/rules/${_seg(id)}',
          body: rule, what: 'save that rule');

  /// `DELETE /books/bank/rules/{id}`.
  Future<Map<String, dynamic>> deleteBankRule(String id) => _map(
      'DELETE', '/books/bank/rules/${_seg(id)}',
      what: 'delete that rule');

  // Contacts (/contacts/*).

  Future<Map<String, dynamic>> contacts() =>
      _map('GET', '/contacts', what: 'load contacts');

  Future<Map<String, dynamic>> refreshContacts() =>
      _map('POST', '/contacts/refresh', what: 'refresh contacts');

  Future<Map<String, dynamic>> editContact(
          String id, Map<String, dynamic> edits) =>
      _map('PUT', '/contacts/${_seg(id)}',
          body: edits, what: 'save that contact');

  /// `GET /contacts/import/{outlook|email}`: every row of that source, each
  /// marked when it is already in the books (`existing_id`, `match`).
  /// Outlook needs `Contacts.Read` on the token, email `Mail.Read`.
  Future<Map<String, dynamic>> importPreview(String source) =>
      _map('GET', '/contacts/import/$source', what: 'read that list');

  /// `POST /contacts/import/check`: the same marking for the phone's rows.
  Future<Map<String, dynamic>> importCheck(
          List<Map<String, dynamic>> rows) =>
      _map('POST', '/contacts/import/check',
          body: {'contacts': rows}, what: 'check those contacts');

  /// `POST /contacts/import`: save the ticked rows (`name`, `person`,
  /// `email`, `phone`, `kind`). Ones already in the books are skipped; the
  /// answer carries `message` ("Imported 10, skipped 2 already in your
  /// books.").
  Future<Map<String, dynamic>> importContacts(
          String source, List<Map<String, dynamic>> rows) =>
      _map('POST', '/contacts/import',
          body: {'source': source, 'contacts': rows},
          what: 'import those contacts');

  /// `POST /contacts/import-outlook`. The Graph token must carry
  /// `Contacts.Read`.
  Future<Map<String, dynamic>> importOutlookContacts({bool addNew = false}) =>
      _map('POST', '/contacts/import-outlook',
          body: {'add_new': addNew}, what: 'import Outlook contacts');

  /// `POST /contacts/import-phone`: save contacts the user picked with the
  /// phone's system picker. Each entry carries the reviewed `name`, `kind`
  /// (`customer` or `supplier`) and whatever the picker returned; the
  /// runtime adds new contacts or fills blank fields and audits the import
  /// with `source: "phone"`. Nothing is written back to the phone.
  Future<Map<String, dynamic>> importPhoneContacts(
          List<Map<String, String?>> contacts) =>
      _map('POST', '/contacts/import-phone',
          body: {'contacts': contacts},
          what: 'import phone contacts');

  Future<Map<String, dynamic>> contactStatement(String id,
          {String? from, String? to}) =>
      _map('GET', '/contacts/${_seg(id)}/statement',
          query: {
            'from': ?from,
            'to': ?to,
          },
          what: 'load that statement');

  Future<Map<String, dynamic>> agedBalances({String? asOf}) =>
      _map('GET', '/contacts/aged',
          query: {'as_of': ?asOf},
          what: 'load aged balances');

  // Company and VAT look-ups (`GET /lookup/*`, `POST /contacts/vat-check`)
  // and possible duplicates (`GET /contacts/duplicates`, merge, undo).
  // Same paths and bodies as the web's `runtime` in
  // `apps/web/src/lib/runtime.ts`. Nothing here saves except the VAT check
  // (kept on the contact) and an approved merge.

  /// `GET /lookup/status` without sign-in: which official look-ups this
  /// reader offers. Null when the reader does not answer (both stay hidden).
  Future<Map<String, dynamic>?> lookupStatus() async {
    try {
      final response = await http
          .get(Uri.parse('${settings.runtimeUrl}/lookup/status'))
          .timeout(const Duration(seconds: 10));
      if (response.statusCode != 200) return null;
      final decoded = json.decode(response.body);
      return decoded is Map ? Map<String, dynamic>.from(decoded) : null;
    } catch (_) {
      return null;
    }
  }

  /// True when [error] is the reader's 503 `companies_house_not_configured`
  /// or `vat_check_not_configured`: the look-up stays hidden, never an error.
  static bool lookupNotConfigured(Object error, String code) =>
      error is RuntimeException && error.message.contains(code);

  /// `GET /lookup/companies?q=`: Companies House matches for a name (or the
  /// one company for a company number). Throws [RuntimeException]; callers
  /// hide the look-up on 503 `companies_house_not_configured`.
  Future<Map<String, dynamic>> lookupCompanies(String q) => _map(
      'GET', '/lookup/companies',
      query: {'q': q}, what: 'look up that company');

  /// `POST /contacts/vat-check`: ask HMRC about [vrn] only when the user
  /// taps. The answer is kept on the contact with that number. Throws
  /// [RuntimeException]; callers hide the check on 503
  /// `vat_check_not_configured`.
  Future<Map<String, dynamic>> vatCheck({
    required String vrn,
    String? name,
    String? contactId,
    bool refresh = false,
  }) =>
      _map('POST', '/contacts/vat-check',
          body: {
            'vrn': vrn,
            'name': ?name,
            'contact_id': ?contactId,
            if (refresh) 'refresh': true,
          },
          what: 'check that VAT number');

  /// `GET /contacts/duplicates`: candidate groups by code (shared email,
  /// phone, VAT number or close name) with the model's view beside each.
  Future<Map<String, dynamic>> duplicates() =>
      _map('GET', '/contacts/duplicates', what: 'load possible duplicates');

  /// `POST /contacts/duplicates/dismiss`: remembered, never suggested again.
  Future<Map<String, dynamic>> dismissDuplicates(List<String> ids) => _map(
      'POST', '/contacts/duplicates/dismiss',
      body: {'contact_ids': ids},
      what: 'note those contacts are not the same');

  /// `POST /contacts/merge`: fold [mergeIds] into [keepId] on approval.
  /// Returns `{contact, merge_id}`; the id undoes the merge.
  Future<Map<String, dynamic>> mergeContacts({
    required String keepId,
    required List<String> mergeIds,
    String? name,
  }) =>
      _map('POST', '/contacts/merge',
          body: {
            'keep_id': keepId,
            'merge_ids': mergeIds,
            'name': ?name,
          },
          what: 'merge those contacts');

  /// `POST /contacts/merge/{mergeId}/undo`: restore the exact previous
  /// entries and references.
  Future<Map<String, dynamic>> undoContactMerge(String mergeId) => _map(
      'POST', '/contacts/merge/${_seg(mergeId)}/undo',
      what: 'undo that merge');

  // Reports (/reports/*). Worked out by code from the ledger; only export
  // writes (one spreadsheet in 07 Reports). Money is integer pence.

  /// Profit and loss. [from]/[to] are `YYYY-MM-DD`; omit both for the VAT
  /// period we are in now (the saved VAT period rides along as the query,
  /// like the web). `GET /reports/pl`.
  Future<Map<String, dynamic>> reportsPl({String? from, String? to}) =>
      _map('GET', '/reports/pl',
          query: {
            ...vatQuery(),
            'from': ?from,
            'to': ?to,
          },
          what: 'load the profit and loss');

  /// Aged debtors and creditors, the same figures as [agedBalances].
  /// `GET /reports/aged` → `{debtors, creditors, as_of, sample}`.
  Future<Map<String, dynamic>> reportsAged() =>
      _map('GET', '/reports/aged', what: 'load aged balances');

  /// VAT boxes per period, oldest first. `GET /reports/vat`, with the
  /// saved VAT period, like the web.
  Future<Map<String, dynamic>> reportsVat({int periods = 4}) =>
      _map('GET', '/reports/vat',
          query: {...vatQuery(), 'periods': '$periods'},
          what: 'load the VAT summary');

  /// Sales, purchases and net per calendar month, oldest first.
  /// `GET /reports/trend`.
  Future<Map<String, dynamic>> reportsTrend({int months = 12}) =>
      _map('GET', '/reports/trend',
          query: {'months': '$months'},
          what: 'load the monthly trend');

  /// Save the report as a spreadsheet in 07 Reports; posts nothing.
  /// `GET /exports/{id}`: one report as JSON (`doc` with its sections), for
  /// the Tax summary of books kept outside the UK.
  Future<Map<String, dynamic>> exportPreview(String id, {String? from, String? to}) =>
      _map('GET', '/exports/${_seg(id)}',
          query: {...vatQuery(), 'from': ?from, 'to': ?to}, what: 'load that report');

  /// `POST /exports/{id}/save`: the report's file saved in 07 Reports.
  Future<Map<String, dynamic>> exportSave(String id, {String format = 'csv', String? from, String? to}) =>
      _map('POST', '/exports/${_seg(id)}/save',
          query: vatQuery(),
          body: {'format': format, 'from': ?from, 'to': ?to},
          what: 'save that report');

  /// `POST /reports/export` → `{path, name, size, sample, sheets}`.
  /// [report] is `pl`, `aged`, `vat`, `trend` or `all`. The saved VAT
  /// period rides along as the query, like the web.
  Future<Map<String, dynamic>> reportExport(
          {String report = 'all', String? from, String? to}) =>
      _map('POST', '/reports/export',
          query: vatQuery(),
          body: {
            'report': report,
            'from': ?from,
            'to': ?to,
          },
          what: 'save that report');

  // Invoices (/invoices/*). Totals and VAT are worked out by the runtime;
  // the phone never computes them.

  /// `GET /invoices`, optionally filtered by [status].
  Future<List<Map<String, dynamic>>> invoices({String? status}) => _list(
      'GET', '/invoices',
      query: {'status': ?status},
      what: 'load invoices');

  /// `GET /invoices/{number}`.
  Future<Map<String, dynamic>> invoice(String number) => _map(
      'GET', '/invoices/${_seg(number)}',
      what: 'load that invoice');

  /// `POST /invoices`: the response carries the priced lines and totals.
  Future<Map<String, dynamic>> createInvoice(Map<String, dynamic> draft) =>
      _map('POST', '/invoices', body: draft, what: 'create that invoice');

  /// `POST /invoices/{number}/pdf`: the preview plus the email draft the
  /// confirmation dialog starts from.
  Future<Map<String, dynamic>> invoicePdf(String number) => _map(
      'POST', '/invoices/${_seg(number)}/pdf',
      what: 'preview that invoice');

  /// `POST /invoices/{number}/send` from the user's Outlook. Call only from
  /// the confirmation dialog: [confirm] is the user's tap, and the Graph
  /// token must carry `Mail.Send`.
  Future<Map<String, dynamic>> sendInvoice(
    String number, {
    required bool confirm,
    String? to,
    String? subject,
    String? body,
  }) {
    final payload = <String, Object?>{'confirm': confirm};
    if (to != null) payload['to'] = to;
    if (subject != null) payload['subject'] = subject;
    if (body != null) payload['body'] = body;
    return _map('POST', '/invoices/${_seg(number)}/send',
        body: payload, what: 'send that invoice');
  }

  /// `GET /invoices/customers`: customers from the contact book, for the picker.
  Future<List<Map<String, dynamic>>> invoiceCustomers() =>
      _list('GET', '/invoices/customers', what: 'load customers');

  /// How the business appears on its invoices (`GET /invoices/profile`,
  /// kept in the user's OneDrive so every device prints the same).
  /// Same path the web's `InvoiceProfileForm` reads.
  /// What these books are (`GET /profile`, services/runtime/app/profile.py):
  /// `name`, `kind` (company | sole_trader | personal), `exists` and
  /// `features`. One Microsoft account is one profile; the web links several,
  /// this phone shows one at a time (Settings › Switch account).
  Future<Map<String, dynamic>> booksProfile() =>
      _map('GET', '/profile', what: 'load the profile');

  /// `PUT /profile`: save the whole profile (`name`, `kind`, `settings`);
  /// `linked` left out keeps the saved list. Settings › Country and tax uses
  /// it for `country`, `sales_tax` and `currency` (services/region.dart).
  Future<Map<String, dynamic>> saveBooksProfile(Map<String, dynamic> body) =>
      _map('PUT', '/profile', body: body, what: 'save the profile');

  Future<Map<String, dynamic>> invoiceProfile() =>
      _map('GET', '/invoices/profile', what: 'load invoice details');

  /// Save the invoice profile (`PUT /invoices/profile`). [profile] keeps
  /// the shape `invoiceProfile()` returned, with the edited fields
  /// replaced — the same body the web sends.
  Future<Map<String, dynamic>> saveInvoiceProfile(
          Map<String, dynamic> profile) =>
      _map('PUT', '/invoices/profile',
          body: profile, what: 'save invoice details');

  // Payments, credit notes and credits. Same paths and bodies as the web's
  // `runtime` in apps/web/src/lib/runtime.ts; money is integer pence and
  // dates are `YYYY-MM-DD`. Every figure is worked out by the runtime.

  /// `POST /invoices/{number}/payments`: part of the balance, all of it, or
  /// more (the rest stays as a credit on the customer). [account] is
  /// `1200 Bank` or `1210 Cash`.
  Future<Map<String, dynamic>> recordInvoicePayment(
    String number, {
    int? amountPence,
    String? paidOn,
    String account = '1200 Bank',
    String? paymentRef,
  }) =>
      _map('POST', '/invoices/${_seg(number)}/payments',
          body: {
            'amount_pence': ?amountPence,
            'paid_on': ?paidOn,
            'account': account,
            if (paymentRef != null && paymentRef.isNotEmpty)
              'payment_ref': paymentRef,
          },
          what: 'record that payment');

  /// `DELETE /invoices/{number}/payments/{paymentId}`: take a payment back.
  Future<Map<String, dynamic>> removeInvoicePayment(
          String number, String paymentId) =>
      _map('DELETE',
          '/invoices/${_seg(number)}/payments/${_seg(paymentId)}',
          what: 'remove that payment');

  /// `POST /invoices/{number}/void` with a reason. Refused (409/400 with the
  /// runtime's sentence) while payments, a matched line or issued credit
  /// notes stand.
  Future<Map<String, dynamic>> voidInvoice(String number, String reason) =>
      _map('POST', '/invoices/${_seg(number)}/void',
          body: {'reason': reason}, what: 'void that invoice');

  /// `POST /invoices/{number}/credit-notes`: credit the whole invoice or
  /// chosen [lines] (`[{line, quantity}]`). Posts at once; the call is made
  /// only from the confirmation sheet, so `confirm` is always true here.
  Future<Map<String, dynamic>> createCreditNote(
    String number, {
    required String reason,
    String? issueDate,
    List<Map<String, String>>? lines,
  }) =>
      _map('POST', '/invoices/${_seg(number)}/credit-notes',
          body: {
            'confirm': true,
            'reason': reason,
            'issue_date': ?issueDate,
            'lines': ?lines,
          },
          what: 'create that credit note');

  /// `GET /credit-notes`, optionally for one invoice.
  Future<List<Map<String, dynamic>>> creditNotes({String? invoice}) => _list(
      'GET', '/credit-notes',
      query: {'invoice': ?invoice},
      what: 'load credit notes');

  /// `POST /payments`: a payment split across open documents (bills to pay
  /// on the phone: side `purchase`). [body] keeps the runtime's shape:
  /// `{side, date?, amount_pence?, account?, reference?, allocations}`.
  Future<Map<String, dynamic>> recordPayment(Map<String, dynamic> body) =>
      _map('POST', '/payments', body: body, what: 'record that payment');

  /// `DELETE /payments/{id}`: reverse a recorded payment.
  Future<Map<String, dynamic>> removePayment(String id) => _map(
      'DELETE', '/payments/${_seg(id)}',
      what: 'remove that payment');

  /// `GET /payments/open`: documents with something left to pay (`side`
  /// `sale` or `purchase`, default `purchase` like the runtime).
  Future<List<Map<String, dynamic>>> openDocuments({String? side}) => _list(
      'GET', '/payments/open',
      query: {'side': ?side},
      what: 'load open documents');

  /// `GET /credits`: money left on contacts' accounts, credit by credit.
  Future<List<Map<String, dynamic>>> credits({String? side}) => _list(
      'GET', '/credits',
      query: {'side': ?side},
      what: 'load credits');

  /// `POST /credits/apply`: put a credit towards another open document of
  /// the same contact. Nothing is posted.
  Future<Map<String, dynamic>> applyCredit({
    required String credit,
    required String eventId,
    int? amountPence,
    String? date,
  }) =>
      _map('POST', '/credits/apply',
          body: {
            'credit': credit,
            'event_id': eventId,
            'amount_pence': ?amountPence,
            'date': ?date,
          },
          what: 'apply that credit');

  /// `POST /credits/refund`: pay a credit back. Posted by the runtime.
  Future<Map<String, dynamic>> refundCredit({
    required String credit,
    int? amountPence,
    String? date,
    String account = '1200 Bank',
    String? reference,
  }) =>
      _map('POST', '/credits/refund',
          body: {
            'credit': credit,
            'amount_pence': ?amountPence,
            'date': ?date,
            'account': account,
            if (reference != null && reference.isNotEmpty)
              'reference': reference,
          },
          what: 'refund that credit');

  /// `DELETE /credits/uses/{useId}`: take an apply or refund back.
  Future<Map<String, dynamic>> removeCreditUse(String useId) => _map(
      'DELETE', '/credits/uses/${_seg(useId)}',
      what: 'take back that credit use');

  // Pay runs (/payroll/runs). Pence throughout; every est_* figure is an
  // estimate for the payroll provider — the phone never confirms.

  /// All pay runs, newest first. `GET /payroll/runs` → `{runs, estimate,
  /// limits, tax_year, source_url}`.
  Future<Map<String, dynamic>> payrollRuns() =>
      _map('GET', '/payroll/runs', what: 'load pay runs');

  // Personal finances (/personal/*). Money is whole pence; every figure is
  // worked out by the runtime from the imported bank statements. Same paths
  // and bodies as the web's `personal` in `apps/web/src/lib/runtime.ts`.

  /// Month summary: money in, spend by category against budget, left over.
  /// `GET /personal/summary?month=YYYY-MM`; [month] defaults to this month
  /// on the runtime when omitted.
  Future<Map<String, dynamic>> personalSummary({String? month}) => _map(
      'GET', '/personal/summary',
      query: {'month': ?month}, what: 'load this month');

  /// Monthly budgets. `GET /personal/budgets` → `{category id: pence}`.
  Future<Map<String, dynamic>> personalBudgets() =>
      _map('GET', '/personal/budgets', what: 'load budgets');

  /// Replace the budgets. `PUT /personal/budgets` with
  /// `{budgets: {category id: pence}}`; 0 or absent means no budget.
  /// The phone reads first and saves the whole map, so one category can be
  /// changed without losing the rest.
  Future<Map<String, dynamic>> savePersonalBudgets(
          Map<String, int> budgets) =>
      _map('PUT', '/personal/budgets',
          body: {'budgets': budgets}, what: 'save that budget');

  /// Recurring bills and subscriptions found in the statements (estimates).
  /// `GET /personal/recurring` → `{items, monthly_total_pence, note}`.
  Future<Map<String, dynamic>> personalRecurring() =>
      _map('GET', '/personal/recurring', what: 'load recurring bills');

  /// Savings goals with the monthly amount the runtime works out.
  /// `GET /personal/goals`.
  Future<List<Map<String, dynamic>>> personalGoals() =>
      _list('GET', '/personal/goals', what: 'load savings goals');

  // Automatic bank sync (/books/bankfeeds, services/runtime/app/
  // routes_bankfeeds.py). Connecting a bank happens on the web; the app shows
  // the status and syncs.

  /// `GET /books/bankfeeds`: whether feeds are available here, and each
  /// connected bank with its last sync.
  Future<Map<String, dynamic>> bankFeeds() =>
      _map('GET', '/books/bankfeeds', what: 'load your bank sync');

  /// `POST /books/bankfeeds/sync`: fetch new lines from every connected bank.
  Future<Map<String, dynamic>> syncBankFeeds() =>
      _map('POST', '/books/bankfeeds/sync', what: 'sync your bank');

  // Goals tracked against the books (/books/goals, services/runtime/app/
  // routes_goals.py). Same paths and bodies as the web's lib/goals.ts.

  /// Every goal with its progress, code's suggestions and the note.
  /// `GET /books/goals?today=YYYY-MM-DD`.
  /// `noteAi: false` asks for code's own note (fast); the AI's note follows.
  Future<Map<String, dynamic>> goals({String? today, bool noteAi = true}) => _map(
      'GET', '/books/goals',
      query: {'today': ?today, if (!noteAi) 'note_ai': 'false'},
      what: 'load your goals');

  /// `POST /books/goals` with the GoalIn body (name, kind, start, end and
  /// target_pence / percent / focus / measure / saved_pence).
  Future<Map<String, dynamic>> addGoal(Map<String, dynamic> goal) =>
      _map('POST', '/books/goals', body: goal, what: 'add that goal');

  /// `GET /notes`: the user's notes, newest first (`_System/notes/notes.json`).
  Future<List<Map<String, dynamic>>> notes() =>
      _list('GET', '/notes', what: 'load your notes');

  /// `POST /notes`: a typed note from the Notes screen (the assistant saves
  /// spoken ones through a card).
  Future<Map<String, dynamic>> addNote(String text) => _map('POST', '/notes',
      body: {'text': text, 'source': 'typed'}, what: 'save that note');

  /// `DELETE /notes/{id}`.
  Future<void> deleteNote(String id) =>
      _json('DELETE', '/notes/${_seg(id)}', what: 'delete that note');

  /// `POST /books/ask/transcribe`: speech to text only — the reply to "Shall
  /// I go ahead?". Nothing is answered or changed.
  Future<String> transcribe(List<int> wavBytes) async {
    _requireBooks();
    final request = http.MultipartRequest('POST', _uri('/books/ask/transcribe'))
      ..headers.addAll(_headers)
      ..files.add(http.MultipartFile.fromBytes('audio', wavBytes,
          filename: 'reply.wav'));
    final streamed = await _http.send(request).timeout(_timeout);
    final body = await streamed.stream.bytesToString();
    if (streamed.statusCode < 200 || streamed.statusCode >= 300) {
      _fail(streamed.statusCode, body.trim());
    }
    final decoded = json.decode(body);
    return decoded is Map ? (decoded['transcript'] ?? '').toString() : '';
  }

  /// `PATCH /books/goals/{id}`, e.g. `{saved_pence: …}` for money put aside.
  Future<Map<String, dynamic>> patchGoal(
          String id, Map<String, dynamic> changes) =>
      _map('PATCH', '/books/goals/${_seg(id)}',
          body: changes, what: 'save that goal');

  /// `DELETE /books/goals/{id}`.
  Future<void> deleteGoal(String id) =>
      _json('DELETE', '/books/goals/${_seg(id)}', what: 'remove that goal');

  /// One pay run with its lines. `GET /payroll/runs/{period}`.
  Future<Map<String, dynamic>> payrollRun(String period) => _map(
      'GET', '/payroll/runs/${_seg(period)}',
      what: 'load that pay run');

  // Jobs, staff and timesheets.

  /// Jobs with their summaries (reads the ledger). `GET /jobs`.
  Future<List<Map<String, dynamic>>> jobs() =>
      _list('GET', '/jobs', what: 'load jobs');

  /// Plain jobs for pickers (no ledger read). `GET /jobs/list`.
  Future<List<Map<String, dynamic>>> jobList({String? status}) =>
      _list('GET', '/jobs/list',
          query: {'status': ?status}, what: 'load jobs');

  Future<Map<String, dynamic>> createJob(Map<String, dynamic> job) =>
      _map('POST', '/jobs', body: job, what: 'add that job');

  Future<Map<String, dynamic>> updateJob(String id, Map<String, dynamic> job) =>
      _map('PUT', '/jobs/${_seg(id)}', body: job, what: 'save that job');

  Future<void> deleteJob(String id) =>
      _json('DELETE', '/jobs/${_seg(id)}', what: 'delete that job');

  Future<Map<String, dynamic>> jobSummary(String id) =>
      _map('GET', '/jobs/${_seg(id)}/summary', what: 'load that job');

  /// Proposed invoice lines from unbilled hours; marks nothing.
  Future<Map<String, dynamic>> jobInvoiceLines(String id) => _map(
      'POST', '/jobs/${_seg(id)}/invoice-lines',
      what: 'propose invoice lines');

  /// Only after the invoice has been sent.
  Future<List<Map<String, dynamic>>> markInvoiced(
          String id, String invoiceId, List<String> entryIds) =>
      _list('POST', '/jobs/${_seg(id)}/mark-invoiced',
          body: {'invoice_id': invoiceId, 'entry_ids': entryIds},
          what: 'mark those hours invoiced');

  Future<List<Map<String, dynamic>>> staff() =>
      _list('GET', '/staff', what: 'load staff');

  Future<Map<String, dynamic>> createStaff(Map<String, dynamic> member) =>
      _map('POST', '/staff', body: member, what: 'add that person');

  Future<Map<String, dynamic>> updateStaff(
          String id, Map<String, dynamic> member) =>
      _map('PUT', '/staff/${_seg(id)}', body: member, what: 'save that person');

  Future<void> deleteStaff(String id) =>
      _json('DELETE', '/staff/${_seg(id)}', what: 'remove that person');

  /// [month] is `YYYY-MM`.
  Future<List<Map<String, dynamic>>> timesheets(
          {String? jobId, String? staffId, String? month}) =>
      _list('GET', '/timesheets',
          query: {
            'job_id': ?jobId,
            'staff_id': ?staffId,
            'month': ?month,
          },
          what: 'load timesheets');

  Future<Map<String, dynamic>> addTimesheet(Map<String, dynamic> entry) =>
      _map('POST', '/timesheets', body: entry, what: 'add those hours');

  Future<Map<String, dynamic>> updateTimesheet(
          String id, Map<String, dynamic> changes) =>
      _map('PUT', '/timesheets/${_seg(id)}',
          body: changes, what: 'save those hours');

  Future<Map<String, dynamic>> deleteTimesheet(String id) => _map(
      'DELETE', '/timesheets/${_seg(id)}',
      what: 'delete those hours');

  // Vehicles and mileage.

  Future<List<Map<String, dynamic>>> vehicles() =>
      _list('GET', '/vehicles', what: 'load vehicles');

  Future<Map<String, dynamic>> addVehicle(Map<String, dynamic> vehicle) =>
      _map('POST', '/vehicles', body: vehicle, what: 'add that vehicle');

  Future<Map<String, dynamic>> updateVehicle(
          String id, Map<String, dynamic> changes) =>
      _map('PATCH', '/vehicles/${_seg(id)}',
          body: changes, what: 'save that vehicle');

  Future<Map<String, dynamic>> deleteVehicle(String id) => _map(
      'DELETE', '/vehicles/${_seg(id)}',
      what: 'delete that vehicle');

  /// [taxYear] is like `2026-27`; default the current one.
  Future<List<Map<String, dynamic>>> mileage({String? taxYear}) =>
      _list('GET', '/mileage',
          query: {'tax_year': ?taxYear},
          what: 'load the mileage log');

  Future<Map<String, dynamic>> addMileage(Map<String, dynamic> journey) =>
      _map('POST', '/mileage', body: journey, what: 'add that journey');

  Future<Map<String, dynamic>> updateMileage(
          String id, Map<String, dynamic> changes) =>
      _map('PATCH', '/mileage/${_seg(id)}',
          body: changes, what: 'save that journey');

  Future<Map<String, dynamic>> deleteMileage(String id) => _map(
      'DELETE', '/mileage/${_seg(id)}',
      what: 'delete that journey');

  Future<Map<String, dynamic>> mileageSummary({String? taxYear}) =>
      _map('GET', '/mileage/summary',
          query: {'tax_year': ?taxYear},
          what: 'load the mileage summary');

  /// The quarter's allowance as a proposal in Review (one per quarter).
  /// [period] is `Q1`–`Q4`. Returns `{proposal, created}`.
  Future<Map<String, dynamic>> proposeAllowance(
          {String? taxYear, String? period}) =>
      _map('POST', '/mileage/propose-allowance',
          query: {
            'tax_year': ?taxYear,
            'period': ?period,
          },
          what: 'claim the mileage allowance');

  // --- parity-b ---
  // The web's editing routes for Bank, household Budget, Settings and Files,
  // so the phone does what the web does (same bodies as apps/web/src/lib/runtime.ts).

  /// `POST /books/bank/import` from bytes the document picker read.
  Future<Map<String, dynamic>> bankImportBytes(String name, List<int> bytes) =>
      _uploadBytes('/books/bank/import', 'file', name, bytes,
          what: 'import that statement');

  /// `POST /books/bank/rules/reorder`: every rule id exactly once.
  Future<List<Map<String, dynamic>>> reorderBankRules(List<String> ids) =>
      _list('POST', '/books/bank/rules/reorder',
          body: {'ids': ids}, what: 'reorder the rules');

  /// `GET /books/bank/lines/{id}/rule-draft`: a rule drafted from one line.
  Future<Map<String, dynamic>> bankRuleDraft(String lineId) => _map(
      'GET', '/books/bank/lines/${_seg(lineId)}/rule-draft',
      what: 'draft a rule from that line');

  Future<List<Map<String, dynamic>>> personalCategories() =>
      _list('GET', '/personal/categories', what: 'load categories');

  /// `PUT /personal/categories`: the whole list; ids kept so budgets and
  /// rules follow a rename, a new one has no id.
  Future<List<Map<String, dynamic>>> savePersonalCategories(
          List<Map<String, dynamic>> categories) =>
      _list('PUT', '/personal/categories',
          body: {'categories': categories}, what: 'save categories');

  Future<List<Map<String, dynamic>>> personalRules() =>
      _list('GET', '/personal/rules', what: 'load spending rules');

  /// `POST /personal/rules`: `{name?, match: {op, value}, category_id}`.
  Future<Map<String, dynamic>> addPersonalRule(Map<String, dynamic> rule) =>
      _map('POST', '/personal/rules', body: rule, what: 'save that rule');

  Future<List<Map<String, dynamic>>> addStarterPersonalRules() =>
      _list('POST', '/personal/rules/starter', what: 'add the starter rules');

  Future<void> deletePersonalRule(String id) =>
      _json('DELETE', '/personal/rules/${_seg(id)}', what: 'delete that rule');

  Future<List<Map<String, dynamic>>> reorderPersonalRules(List<String> ids) =>
      _list('POST', '/personal/rules/reorder',
          body: {'ids': ids}, what: 'reorder the rules');

  /// Put one bank line in a category by hand; null hands it back to the rules.
  Future<void> setLineCategory(String lineId, String? categoryId) => _json(
      'POST', '/personal/lines/${_seg(lineId)}/category',
      body: {'category_id': categoryId}, what: 'set that category');

  /// `POST /mail/mailboxes`: link a shared mailbox (work accounts) by address.
  Future<Map<String, dynamic>> addMailbox(Map<String, dynamic> body) =>
      _map('POST', '/mail/mailboxes', body: body, what: 'link that mailbox');

  /// `PATCH /mail/mailboxes/{id}`: folder and sender filters.
  Future<Map<String, dynamic>> updateMailbox(
          String id, Map<String, dynamic> changes) =>
      _map('PATCH', '/mail/mailboxes/${_seg(id)}',
          body: changes, what: 'save that mailbox');

  Future<Map<String, dynamic>> removeMailbox(String id) => _map(
      'DELETE', '/mail/mailboxes/${_seg(id)}', what: 'remove that mailbox');

  /// `POST /invoices/profile/logo`: a PNG or JPEG up to 1 MB.
  Future<Map<String, dynamic>> uploadInvoiceLogo(String name, List<int> bytes) =>
      _uploadBytes('/invoices/profile/logo', 'file', name, bytes,
          what: 'save the logo');

  /// `POST /files/trash`: Clean up moves these documents to _Trash (at most
  /// 200 a call); documents the books link to are refused by the runtime.
  Future<Map<String, dynamic>> trashFiles(List<String> paths) =>
      _map('POST', '/files/trash', body: {'paths': paths}, what: 'clean up');

  Future<Map<String, dynamic>> _uploadBytes(
    String path,
    String field,
    String name,
    List<int> bytes, {
    required String what,
  }) async {
    _requireBooks();
    final request =
        http.MultipartRequest('POST', Uri.parse('${settings.runtimeUrl}$path'))
          ..headers.addAll(_headers)
          ..files.add(http.MultipartFile.fromBytes(field, bytes, filename: name));
    final decoded = await _send(request, what);
    return decoded is Map ? Map<String, dynamic>.from(decoded) : {};
  }
  // --- end parity-b ---

  static String _seg(String s) => Uri.encodeComponent(s);

  /// One books call with an optional JSON [body]. [what] completes
  /// "Could not …" in errors. Returns the decoded JSON, or null for 204.
  Future<dynamic> _json(
    String method,
    String path, {
    Object? body,
    Map<String, String> query = const {},
    required String what,
  }) async {
    _requireBooks();
    var uri = Uri.parse('${settings.runtimeUrl}$path');
    if (query.isNotEmpty) uri = uri.replace(queryParameters: query);
    final request = http.Request(method, uri)..headers.addAll(_headers);
    if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = json.encode(body);
    }
    return _send(request, what);
  }

  // --- parity-a --- month-end runs, pay runs, staff, accountant and queries,
  // with the same routes and bodies as the web (apps/web/src/lib/runtime.ts).

  /// `POST /close/{month}/run`: work through the nine-step checklist. Posts
  /// nothing; what needs the owner comes back as signed cards (`actions`) to
  /// approve with [approveAction], the `close_month` card among them.
  Future<Map<String, dynamic>> runClose(String month, {String? today}) =>
      _map('POST', '/close/${_seg(month)}/run',
          body: {'outlook': false},
          query: {'today': ?today},
          what: 'run the month-end close');

  /// `POST /payroll/runs/prepare`: a draft run from that month's timesheets.
  Future<Map<String, dynamic>> preparePayRun(String period, {String? payDate}) =>
      _map('POST', '/payroll/runs/prepare',
          body: {'period': period, 'pay_date': payDate},
          what: 'prepare that pay run');

  /// `PUT /payroll/runs/{period}`: hours, rates and notes per person.
  Future<Map<String, dynamic>> editPayRun(
          String period, List<Map<String, dynamic>> lines, {String? payDate}) =>
      _map('PUT', '/payroll/runs/${_seg(period)}',
          body: {'lines': lines, 'pay_date': payDate},
          what: 'save that pay run');

  /// `POST /payroll/runs/{period}/export`: saves `05 Payroll/<period>.csv` in
  /// the books and returns `{path, csv, estimate}`.
  Future<Map<String, dynamic>> exportPayRun(String period) =>
      _map('POST', '/payroll/runs/${_seg(period)}/export',
          what: 'export that pay run');

  /// `POST /payroll/runs/{period}/confirm`: the figures the payroll provider
  /// calculated (not the estimate); this posts the wages journal.
  Future<Map<String, dynamic>> confirmPayRun(
          String period, int actualGrossPence, int actualErNiPence) =>
      _map('POST', '/payroll/runs/${_seg(period)}/confirm',
          body: {
            'actual_gross_pence': actualGrossPence,
            'actual_er_ni_pence': actualErNiPence,
          },
          what: 'confirm that pay run');

  /// `POST /payroll/runs/{period}/reopen`: undoes the journal, back to draft.
  Future<Map<String, dynamic>> reopenPayRun(String period) =>
      _map('POST', '/payroll/runs/${_seg(period)}/reopen',
          what: 'reopen that pay run');

  /// `POST /accountant/invitations`: [method] `graph` shares the books folder
  /// through Microsoft; `manual` records the invitation and you share it.
  Future<Map<String, dynamic>> inviteAccountant({
    required String email,
    required String name,
    required String role,
    required String method,
    String message = '',
  }) =>
      _map('POST', '/accountant/invitations',
          body: {
            'email': email,
            'name': name,
            'role': role,
            'method': method,
            'message': message,
          },
          what: 'invite your accountant');

  /// `POST /accountant/invitations/{id}/revoke`.
  Future<Map<String, dynamic>> revokeAccountant(String id) => _map(
      'POST', '/accountant/invitations/${_seg(id)}/revoke',
      what: 'remove that access');

  /// `POST /queries/{id}/messages`: answer your accountant.
  Future<Map<String, dynamic>> replyQuery(String id, String text) => _map(
      'POST', '/queries/${_seg(id)}/messages',
      body: {'text': text}, what: 'send that answer');

  /// `POST /queries/{id}/resolve`.
  Future<Map<String, dynamic>> resolveQuery(String id) => _map(
      'POST', '/queries/${_seg(id)}/resolve', what: 'mark that resolved');

  // --- end parity-a ---

  Future<Map<String, dynamic>> _map(
    String method,
    String path, {
    Object? body,
    Map<String, String> query = const {},
    required String what,
  }) async {
    final decoded =
        await _json(method, path, body: body, query: query, what: what);
    return decoded is Map ? Map<String, dynamic>.from(decoded) : {};
  }

  Future<List<Map<String, dynamic>>> _list(
    String method,
    String path, {
    Object? body,
    Map<String, String> query = const {},
    required String what,
  }) async {
    final decoded =
        await _json(method, path, body: body, query: query, what: what);
    if (decoded is! List) return [];
    return [
      for (final x in decoded)
        if (x is Map) Map<String, dynamic>.from(x),
    ];
  }

  /// Multipart upload of [file] as [field], plus plain form [fields].
  Future<Map<String, dynamic>> _upload(
    String path,
    String field,
    File file, {
    Map<String, String> fields = const {},
    required String what,
  }) async {
    _requireBooks();
    final request =
        http.MultipartRequest('POST', Uri.parse('${settings.runtimeUrl}$path'))
          ..headers.addAll(_headers)
          ..fields.addAll(fields)
          ..files.add(await http.MultipartFile.fromPath(field, file.path));
    final decoded = await _send(request, what);
    return decoded is Map ? Map<String, dynamic>.from(decoded) : {};
  }

  Future<dynamic> _send(http.BaseRequest request, String what) async {
    try {
      final streamed = await _http.send(request).timeout(_timeout);
      final text = await streamed.stream.bytesToString();
      if (streamed.statusCode < 200 || streamed.statusCode >= 300) {
        _fail(streamed.statusCode, text.trim());
      }
      if (request.method != 'GET' && _changesBooks(request.url.path)) {
        BooksEvents.bump();
      }
      return text.isEmpty ? null : json.decode(text);
    } on TimeoutException {
      throw RuntimeException(
          'Could not $what: the reader took too long. Try again.');
    } on SocketException {
      throw RuntimeException(
          'Could not reach the reader at ${settings.runtimeUrl}. '
          'Is it running?');
    } on RuntimeException {
      rethrow;
    } catch (e) {
      throw RuntimeException('Could not $what. $e');
    }
  }

  /// Whether a successful non-GET to [path] changed the books (asking a
  /// question, reading a photo or starting a demo did not).
  static bool _changesBooks(String path) => !const [
        '/ask', '/extract', '/demo', '/ai', '/voice', '/stt', '/lookup',
        '/public',
      ].any(path.startsWith);

  Never _fail(int status, String body) {
    if (Demo.active && (status == 401 || status == 404) && _demoGone(body)) {
      // The runtime forgot this demo (two idle hours, or a restart): start
      // a fresh one of the same kind; the screen's retry then works.
      unawaited(Demo.renew());
      throw RuntimeException(
          'The demo had timed out, so a fresh one has started. Pull down to reload.');
    }
    final detail = body.length > 300 ? '${body.substring(0, 300)}…' : body;
    throw RuntimeException(
        'The reader refused that request (status $status). $detail');
  }
}

/// A 401/404 that means the demo session is gone (not a missing record).
bool _demoGone(String body) {
  final b = body.toLowerCase();
  return b.contains('demo') ||
      b.contains('x-graph-token') ||
      b.contains('sign in') ||
      b.contains('not authenticated') ||
      b.contains('token');
}

/// Result of `POST /books/scan`: new proposals plus one entry per file
/// the reader could not read.
class ScanOutcome {
  ScanOutcome({required this.proposals, required this.errors});
  final List<Map<String, dynamic>> proposals;
  final List<ScanFileError> errors;
}

/// Transcript plus checked answer from `POST /books/ask/voice`.
///
/// `answer` is null when the runtime transcribed but could not answer;
/// the transcript still goes in the user's bubble and typing takes over.
class VoiceAnswer {
  VoiceAnswer({required this.transcript, this.answer, this.transcribedBy});
  final String transcript;
  final AskAnswer? answer;

  /// Which speech-to-text service heard it (`transcribed_by.label`), e.g.
  /// "Muse Voice Transcribe" or "a local fallback model"; null if unsaid.
  final String? transcribedBy;

  factory VoiceAnswer.fromJson(Map<String, dynamic> json) {
    final transcript = (json['transcript'] ??
            json['text'] ??
            json['question'] ??
            '')
        .toString();
    AskAnswer? answer;
    final rawAnswer =
        json['answer'] is Map ? json['answer'] : json;
    if (rawAnswer is Map &&
        (rawAnswer['answer_md'] ?? '').toString().isNotEmpty) {
      answer = AskAnswer.fromJson(
          Map<String, dynamic>.from(rawAnswer));
    }
    final by = json['transcribed_by'];
    final label = by is Map ? (by['label'] ?? '').toString().trim() : '';
    return VoiceAnswer(
      transcript: transcript,
      answer: answer,
      transcribedBy: label.isEmpty ? null : label,
    );
  }
}

/// One entry the Autopilot approved on the user's behalf: a posted
/// proposal with `decided_by == 'autopilot'` and a ledger `event_id` that
/// `POST /books/undo/{event_id}` can reverse.
class AutopilotApproval {
  AutopilotApproval({
    required this.proposalId,
    required this.supplier,
    required this.total,
    required this.eventId,
    this.decidedAt,
  });

  final String proposalId;
  final String supplier;
  final double total;
  final String eventId;
  final String? decidedAt;

  /// Keep only Autopilot-decided postings that carry an event id.
  static List<AutopilotApproval> fromProposals(
      List<Map<String, dynamic>> raw) {
    final items = <AutopilotApproval>[];
    for (final json in raw) {
      if ((json['decided_by'] ?? '').toString() != 'autopilot') continue;
      final eventId = (json['event_id'] ?? '').toString();
      if (eventId.isEmpty) continue;
      final extracted = json['extracted'] is Map
          ? Map<String, dynamic>.from(json['extracted'] as Map)
          : <String, dynamic>{};
      final gross = extracted['gross_total'];
      items.add(AutopilotApproval(
        proposalId: (json['id'] ?? '').toString(),
        supplier: (extracted['supplier_name'] ?? 'Unknown supplier')
            .toString(),
        total: gross is num
            ? gross.toDouble()
            : double.tryParse(gross.toString()) ?? 0,
        eventId: eventId,
        decidedAt: json['decided_at']?.toString(),
      ));
    }
    return items;
  }
}

/// One unreadable inbox file from `POST /books/scan`.
class ScanFileError {
  ScanFileError({required this.path, required this.error});
  final String path;
  final String error;

  factory ScanFileError.fromJson(Map<String, dynamic> json) {
    return ScanFileError(
      path: (json['path'] ?? 'Unknown file').toString(),
      error: (json['error'] ?? 'Could not be read').toString(),
    );
  }
}
