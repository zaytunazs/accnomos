import 'package:flutter_test/flutter_test.dart';
import 'package:msal_auth/msal_auth.dart';

import 'package:accnomos_mobile/services/sign_in_messages.dart';

void main() {
  test('cancelled sign-in is friendly', () {
    const error = MsalUserCancelException(
      message: 'User cancelled the flow',
      correlationId: 'x',
    );
    expect(
      friendlySignInMessage(error),
      contains('Sign-in was cancelled'),
    );
  });

  test('redirect or signature mismatch names the build registration', () {
    const error = MsalClientException(
      errorCode: 'malformed_url',
      message: 'The redirect URI is missing the signature hash',
      correlationId: 'x',
    );
    expect(
      friendlySignInMessage(error),
      contains('signature is not registered with Microsoft yet'),
    );
  });

  test('no network asks for a connection check', () {
    const error = MsalClientException(
      errorCode: 'device_network_not_available',
      message: 'No active network is available',
      correlationId: 'x',
    );
    expect(
      friendlySignInMessage(error),
      contains('Check your connection'),
    );
  });

  test('other MSAL errors stay short and never raw', () {
    const error = MsalServiceException(
      errorCode: 'access_denied',
      httpStatusCode: 400,
      message: 'interaction_required',
      correlationId: 'abc',
    );
    final message = friendlySignInMessage(error);
    expect(message, startsWith('Could not sign you in.'));
    expect(message, isNot(contains('MsalServiceException')));
    expect(message, isNot(contains('abc')));
  });

  test('non-MSAL errors get a generic friendly line', () {
    final message = friendlySignInMessage(Exception('vault locked'));
    expect(message, contains('Could not sign you in'));
    expect(message, isNot(contains('Exception:')));
  });
}
