import 'package:flutter/services.dart';

/// Files shared into Accnomos from another app (gallery, email).
///
/// The Android side declares an `ACTION_SEND` intent filter and stages the
/// shared content into its own cache directory, then hands Dart plain file
/// paths over this channel — no extra package needed. Elsewhere (or in
/// tests without the native side) the channel is absent and this returns
/// an empty list.
class ShareIntent {
  static const _channel = MethodChannel('accnomos/share');

  /// Paths staged by the native side since the last call (then cleared).
  static Future<List<String>> initialSharedFiles() async {
    try {
      final result = await _channel.invokeMethod<List>('getSharedFiles');
      if (result == null) return const [];
      return [
        for (final entry in result)
          if (entry is String && entry.isNotEmpty) entry,
      ];
    } on MissingPluginException {
      return const [];
    } on PlatformException {
      return const [];
    }
  }
}
