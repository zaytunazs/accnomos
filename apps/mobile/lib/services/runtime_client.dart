import 'dart:async';
import 'dart:convert';
import 'dart:io';

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
  RuntimeClient(this.settings, {this.books});
  final AppSettings settings;

  /// Present for every books call; null when nobody is signed in.
  final BooksAuth? books;

  // Glimmer on a home machine takes 20–60 s per receipt; the runtime itself is fast.
  static const _timeout = Duration(seconds: 120);

  Map<String, String> get _headers {
    final headers = <String, String>{
      'X-AI-Mode': settings.aiMode,
      'X-AI-Base-Url': settings.aiBaseUrl,
      'X-AI-Model': settings.aiModel,
    };
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
      final streamed = await request.send().timeout(_timeout);
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
      final response = await http
          .post(
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
  /// `POST /books/scan` → `{proposals, errors}`.
  Future<ScanOutcome> scan() async {
    _requireBooks();
    final uri = Uri.parse('${settings.runtimeUrl}/books/scan');
    try {
      final response = await http
          .post(
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
          await http.get(uri, headers: _headers).timeout(_timeout);
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
      final response = await http
          .post(
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
      final response = await http
          .post(
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
          await http.get(uri, headers: _headers).timeout(_timeout);
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

  /// The 9 VAT boxes for the current period. `GET /books/vat`.
  Future<Map<String, dynamic>> vat() async {
    _requireBooks();
    final uri = Uri.parse('${settings.runtimeUrl}/books/vat');
    try {
      final response =
          await http.get(uri, headers: _headers).timeout(_timeout);
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
      throw RuntimeException('Could not load the VAT return. $e');
    }
  }

  /// Ask the books a question. `POST /books/ask` → a checked [AskAnswer].
  /// [periodStart]/[periodEnd] are `YYYY-MM-DD`; omit both for the current
  /// VAT quarter. Only the last six [history] turns are sent.
  Future<AskAnswer> ask(
    String question, {
    String? periodStart,
    String? periodEnd,
    List<AskTurn> history = const [],
  }) async {
    _requireBooks();
    final uri = Uri.parse('${settings.runtimeUrl}/books/ask');
    final recent =
        history.length > 6 ? history.sublist(history.length - 6) : history;
    try {
      final response = await http
          .post(
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
      final response = await http
          .post(
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
    final uri = Uri.parse('${settings.runtimeUrl}/books/ask/voice');
    try {
      final request = http.MultipartRequest('POST', uri)
        ..headers.addAll(_headers)
        ..files.add(http.MultipartFile.fromBytes(
          'audio',
          wavBytes,
          filename: filename,
        ));
      final streamed = await request.send().timeout(_timeout);
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
      final response = await http
          .get(uri, headers: _headers)
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
      final response = await http
          .post(
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
      final response = await http
          .get(Uri.parse('${settings.runtimeUrl}/health'))
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

  /// `GET /books/deadlines`. Send [stagger] (1–3) or [startMonth]; [months]
  /// is 3 (quarterly) or 1 (monthly).
  Future<Map<String, dynamic>> deadlines(
          {int? stagger, int? startMonth, int months = 3, String? today}) =>
      _map('GET', '/books/deadlines',
          query: {
            if (stagger != null) 'stagger': '$stagger',
            if (startMonth != null) 'start_month': '$startMonth',
            'months': '$months',
            'today': ?today,
          },
          what: 'load VAT deadlines');

  /// `POST /mail/scan`. The Graph token must carry `Mail.Read`.
  Future<Map<String, dynamic>> mailScan(
          {int sinceDays = 14, bool dryRun = false}) =>
      _map('POST', '/mail/scan',
          body: {'since_days': sinceDays, 'dry_run': dryRun},
          what: 'check the inbox');

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

  // Contacts (/contacts/*).

  Future<Map<String, dynamic>> contacts() =>
      _map('GET', '/contacts', what: 'load contacts');

  Future<Map<String, dynamic>> refreshContacts() =>
      _map('POST', '/contacts/refresh', what: 'refresh contacts');

  Future<Map<String, dynamic>> editContact(
          String id, Map<String, String?> edits) =>
      _map('PUT', '/contacts/${_seg(id)}',
          body: edits, what: 'save that contact');

  /// `POST /contacts/import-outlook`. The Graph token must carry
  /// `Contacts.Read`.
  Future<Map<String, dynamic>> importOutlookContacts({bool addNew = false}) =>
      _map('POST', '/contacts/import-outlook',
          body: {'add_new': addNew}, what: 'import Outlook contacts');

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
      final streamed = await request.send().timeout(_timeout);
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
