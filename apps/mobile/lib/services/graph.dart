import 'dart:convert';

import 'package:http/http.dart' as http;

import 'auth.dart';

/// OneDrive access for the user's own books folder. Dart port of the folder
/// logic in `apps/web/src/lib/graph.ts`.
///
/// Personal accounts live under the OneDrive app folder (`Apps/Accnomos`);
/// work accounts use `/Accnomos` in the drive root.
class GraphService {
  GraphService({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;

  static const _graph = 'https://graph.microsoft.com/v1.0';

  /// Graph path of an item inside the books folder (path-based addressing).
  static String itemPath(AccountKind kind, [String relPath = '']) {
    final encoded =
        relPath.split('/').map(Uri.encodeComponent).join('/');
    if (kind == AccountKind.personal) {
      return relPath.isEmpty
          ? '/me/drive/special/approot'
          : '/me/drive/special/approot:/$encoded';
    }
    return relPath.isEmpty
        ? '/me/drive/root:/Accnomos'
        : '/me/drive/root:/Accnomos/$encoded';
  }

  Future<Map<String, dynamic>> _json(
    String token,
    String path, {
    String method = 'GET',
    Map<String, dynamic>? body,
  }) async {
    final response = await _client
        .send(
          http.Request(method, Uri.parse('$_graph$path'))
            ..headers['Authorization'] = 'Bearer $token'
            ..headers['Content-Type'] = 'application/json'
            ..body = body == null ? '' : json.encode(body),
        )
        .then(http.Response.fromStream)
        .timeout(const Duration(seconds: 60));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw GraphException(
        'OneDrive refused that request (status ${response.statusCode}). '
        '${response.body.trim().take300}',
      );
    }
    if (response.body.isEmpty) return <String, dynamic>{};
    return json.decode(response.body) as Map<String, dynamic>;
  }

  /// The books root (created on first call for personal accounts).
  Future<Map<String, dynamic>> ensureRoot(
    String token,
    AccountKind kind,
  ) async {
    if (kind == AccountKind.personal) {
      return _json(token, '/me/drive/special/approot');
    }
    try {
      return await _json(token, itemPath(kind));
    } on GraphException {
      return _json(
        token,
        '/me/drive/root/children',
        method: 'POST',
        body: {
          'name': 'Accnomos',
          'folder': {},
          '@microsoft.graph.conflictBehavior': 'fail',
        },
      );
    }
  }

  /// Get-or-create a folder such as `00 Inbox`. Lookup is path-based;
  /// creation is id-based because POST on the `special/approot` alias fails.
  Future<void> ensureFolder(
    String token,
    AccountKind kind,
    String relPath,
  ) async {
    try {
      await _json(token, itemPath(kind, relPath));
      return;
    } on GraphException {
      // Missing — create it under its parent.
    }
    final parts = relPath.split('/');
    final name = parts.removeLast();
    final parent = parts.isEmpty
        ? await ensureRoot(token, kind)
        : await _ensureFolderJson(token, kind, parts.join('/'));
    await _json(
      token,
      '/me/drive/items/${parent['id']}/children',
      method: 'POST',
      body: {
        'name': name,
        'folder': {},
        '@microsoft.graph.conflictBehavior': 'fail',
      },
    );
  }

  Future<Map<String, dynamic>> _ensureFolderJson(
    String token,
    AccountKind kind,
    String relPath,
  ) async {
    try {
      return await _json(token, itemPath(kind, relPath));
    } on GraphException {
      // Missing — create it under its parent.
    }
    final parts = relPath.split('/');
    final name = parts.removeLast();
    final parent = parts.isEmpty
        ? await ensureRoot(token, kind)
        : await _ensureFolderJson(token, kind, parts.join('/'));
    return _json(
      token,
      '/me/drive/items/${parent['id']}/children',
      method: 'POST',
      body: {
        'name': name,
        'folder': {},
        '@microsoft.graph.conflictBehavior': 'fail',
      },
    );
  }

  /// Small-file upload (up to 4 MB), the same call the web's
  /// `UploadToInbox.tsx` makes: Graph PUT to the `00 Inbox` folder.
  Future<void> putFileBytes({
    required String token,
    required AccountKind kind,
    required String relPath,
    required List<int> bytes,
    required String contentType,
  }) async {
    final response = await _client
        .put(
          Uri.parse('$_graph${itemPath(kind, relPath)}:/content'),
          headers: {
            'Authorization': 'Bearer $token',
            'Content-Type': contentType,
          },
          body: bytes,
        )
        .timeout(const Duration(seconds: 120));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw GraphException(
        'Upload failed (status ${response.statusCode}). '
        '${response.body.trim().take300}',
      );
    }
  }

  void close() => _client.close();
}

/// Error from OneDrive. [message] is safe to show in the UI.
class GraphException implements Exception {
  GraphException(this.message);
  final String message;

  @override
  String toString() => message;
}

extension on String {
  String get take300 =>
      length > 300 ? '${substring(0, 300)}…' : this;
}
