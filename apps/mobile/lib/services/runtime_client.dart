import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import 'settings.dart';

/// Error from the reader service. [message] is safe to show in the UI.
class RuntimeException implements Exception {
  RuntimeException(this.message);
  final String message;

  @override
  String toString() => message;
}

/// Talks to the Accnomos reader runtime (`{runtimeUrl}/extract`,
/// `{runtimeUrl}/ai/test`).
class RuntimeClient {
  RuntimeClient(this.settings);
  final AppSettings settings;

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
    return headers;
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

  Never _fail(int status, String body) {
    final detail = body.length > 300 ? '${body.substring(0, 300)}…' : body;
    throw RuntimeException(
        'The reader refused that request (status $status). $detail');
  }
}
