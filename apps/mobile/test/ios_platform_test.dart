import 'package:accnomos_mobile/services/auth.dart';
import 'package:accnomos_mobile/services/google_auth.dart';
import 'package:accnomos_mobile/services/store_policy.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('iOS never links to a purchase; Android and others keep their links', () {
    expect(StorePolicy.purchaseLinksAllowedOn(TargetPlatform.iOS), isFalse);
    expect(StorePolicy.purchaseLinksAllowedOn(TargetPlatform.android), isTrue);
  });

  test('MSAL iOS redirect matches the scheme in ios/Runner/Info.plist', () {
    expect(AuthService.appleRedirectUri, 'msauth.com.accnomos.app://auth');
    expect(AuthService.appleAuthority, 'https://login.microsoftonline.com/common');
  });

  test('Google sign-in is hidden on every platform without client ids', () {
    // Test builds get no --dart-define, so nothing is configured.
    expect(GoogleAuth.configured, isFalse);
    for (final p in TargetPlatform.values) {
      expect(GoogleAuth.supportedOn(p), isFalse, reason: p.name);
    }
  });
}
