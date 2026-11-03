import 'package:flutter/services.dart';

/// The Android share sheet for text the app made (a CSV export, say), through
/// MainActivity's `accnomos/share` channel. No file provider and no extra
/// permission: the text goes in the share intent itself.
class ShareText {
  static const _channel = MethodChannel('accnomos/share');

  /// Test hook: replaces the platform call (returns whether a sheet opened).
  static Future<bool> Function(String text, String subject, String mime)? testHook;

  /// Opens the share sheet; false when the phone could not (no app to share to).
  static Future<bool> share(String text,
      {String subject = 'Accnomos', String mime = 'text/plain'}) async {
    final hook = testHook;
    if (hook != null) return hook(text, subject, mime);
    try {
      final ok = await _channel.invokeMethod<bool>(
          'shareText', {'text': text, 'subject': subject, 'mime': mime});
      return ok ?? false;
    } on PlatformException {
      return false;
    } on MissingPluginException {
      return false;
    }
  }
}
