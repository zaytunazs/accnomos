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

/// Talks to the Accnomos reader runtime (`{runtimeUrl}/extract`,
/// `{runtimeUrl}/ai/test`, `{runtimeUrl}/books/*`).
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
