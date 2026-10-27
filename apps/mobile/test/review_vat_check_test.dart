import 'package:accnomos_mobile/screens/review_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The review card's VAT check: offered only for a purchase with a supplier
/// VAT number while the reader is configured for it; Approve never waits.
/// The tap behaviour itself is covered in `vat_check_test.dart` against the
/// same `VatCheckSection` the card uses.
void main() {
  const channel = MethodChannel('msal_auth');

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      throw PlatformException(
          code: 'NO_CURRENT_ACCOUNT', message: 'no account');
    });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  test('showReviewVatCheck gates the card offer', () {
    bool show({
      bool signedIn = true,
      String? vrn = 'GB882431902',
      String docType = 'receipt',
      Map<String, dynamic>? lookups = const {'vat_check': true},
    }) =>
        showReviewVatCheck(
            signedIn: signedIn,
            supplierVrn: vrn,
            docType: docType,
            lookups: lookups);

    expect(show(), isTrue);
    expect(show(signedIn: false), isFalse);
    expect(show(vrn: null), isFalse);
    expect(show(vrn: '  '), isFalse);
    expect(show(docType: 'sales_invoice'), isFalse);
    expect(show(lookups: const {'vat_check': false}), isFalse);
    expect(show(lookups: null), isFalse);
  });

  testWidgets('signed out, cards offer no VAT check', (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const MaterialApp(home: ReviewScreen()));
    await tester.pumpAndSettle();
    // Sample cards are up, but the check stays hidden without sign-in
    // and without the reader saying it is configured.
    expect(find.text('Check VAT number'), findsNothing);
    expect(find.text('Approve'), findsWidgets);
    expect(tester.takeException(), isNull);
  });
}
