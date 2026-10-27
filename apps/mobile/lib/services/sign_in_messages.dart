import 'package:msal_auth/msal_auth.dart';

/// Friendly sign-in failures. MSAL errors are technical (redirect URIs,
/// broker codes, correlation ids); the UI must never show a raw exception
/// or stack trace, so every path below returns a plain-English line.
String friendlySignInMessage(Object error) {
  if (error is MsalUserCancelException) {
    return 'Sign-in was cancelled. Nothing changed — try again when ready.';
  }
  final detail = error is MsalException
      ? error.message.trim()
      : error.toString().replaceFirst('Exception: ', '').trim();
  final lower = detail.toLowerCase();
  final redirect = lower.contains('redirect') ||
      lower.contains('signature') ||
      lower.contains('hash mismatch') ||
      lower.contains('no activity found') ||
      lower.contains('broker');
  if (redirect) {
    return "This build's signature is not registered with Microsoft yet. "
        'Sign-in cannot complete until the app registration knows this build.';
  }
  final client = error is MsalClientException ? error : null;
  final networkCode = client != null &&
      (client.errorCode == 'device_network_not_available' ||
          client.errorCode == 'io_error');
  final network = networkCode ||
      lower.contains('network') ||
      lower.contains('socket') ||
      lower.contains('connection') ||
      lower.contains('timeout') ||
      lower.contains('unreachable') ||
      lower.contains('failed host') ||
      lower.contains('no address associated');
  if (network) {
    return 'Could not reach Microsoft. Check your connection and try again.';
  }
  if (detail.isNotEmpty) {
    final short =
        detail.length > 220 ? '${detail.substring(0, 220)}…' : detail;
    return 'Could not sign you in. $short';
  }
  return 'Could not sign you in. Please try again.';
}
