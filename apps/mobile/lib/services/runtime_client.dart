import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart' show visibleForTesting;
import 'package:http/http.dart' as http;

import '../models/ask_answer.dart';
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
    final headers = <String, String>{
      'X-AI-Mode': settings.aiMode,
      'X-AI-Base-Url': settings.aiBaseUrl,
      'X-AI-Model': settings.aiModel,
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

  /// Send [image] to the runtime and return the decoded JSON response.
  Future<Map<String, dynamic>> extract(File image) async {
    final uri = Uri.parse('${settings.runtimeUrl}/extract');
    try {
      final request = http.MultipartRequest('POST', uri)
        ..headers.addAll(_headers)
        ..files.add(await http.MultipartFile.fromPath('file', image.path));
      final streamed = await _http.send(request).timeout(_timeout);
      final body = await streamed.stream.bytesToString();
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

  /// Ask the runtime whether the configured AI answers.
  Future<Map<String, dynamic>> aiTest() async {
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
  Future<String> approveAction(ProposedAction action) =>
      _action('approve', action, 'Could not approve that');

  /// `POST /actions/reject`: nothing happens except a line in the audit log.
  Future<String> rejectAction(ProposedAction action) =>
      _action('reject', action, 'Could not reject that');

  Future<String> _action(
    String verb,
    ProposedAction action,
    String what,
  ) async {
    _requireBooks();
    final uri = Uri.parse('${settings.runtimeUrl}/actions/$verb');
    try {
      final response = await _http.post(
            uri,
            headers: {..._headers, 'Content-Type': 'application/json'},
            body: json.encode({'action': action.raw}),
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
  }) async {
    _requireBooks();
    final uri = _uri('/books/ask/voice');
    try {
      final request = http.MultipartRequest('POST', uri)
        ..headers.addAll(_headers)
        ..files.add(http.MultipartFile.fromBytes(
          'audio',
          wavBytes,
          filename: filename,
        ));
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

  /// `POST /books/export`: everything as one zip in `07 Reports/Exports`
  /// (a second run the same day is kept beside the first). Posts nothing.
  /// Same call as the web's Settings › Your data button.
  Future<Map<String, dynamic>> booksExport() => _map('POST', '/books/export',
      what: 'export your data');

  /// To-dos in `_System/Todos/todos.json`. `GET /todos`, soonest first.
  Future<List<Map<String, dynamic>>> todos() =>
      _list('GET', '/todos', what: 'load to-dos');

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

  // Bank statements (/books/bank/*).

  /// `POST /books/bank/import`: the same file twice changes nothing.
  Future<Map<String, dynamic>> bankImport(File csv) =>
      _upload('/books/bank/import', 'file', csv,
          what: 'import that statement');

  Future<List<Map<String, dynamic>>> bankStatements() =>
      _list('GET', '/books/bank/statements', what: 'load bank statements');

  /// [status]: unmatched, matched, suggested, transfer or ignored.
  Future<List<Map<String, dynamic>>> bankLines({String? status}) =>
      _list('GET', '/books/bank/lines',
          query: {'status': ?status},
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

  Never _fail(int status, String body) {
    final detail = body.length > 300 ? '${body.substring(0, 300)}…' : body;
    throw RuntimeException(
        'The reader refused that request (status $status). $detail');
  }
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
  VoiceAnswer({required this.transcript, this.answer});
  final String transcript;
  final AskAnswer? answer;

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
    return VoiceAnswer(transcript: transcript, answer: answer);
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
