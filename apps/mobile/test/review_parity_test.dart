import 'package:accnomos_mobile/screens/review_screen.dart';
import 'package:accnomos_mobile/widgets/review_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Review parity at 360 dp, signed out: every card affordance works
/// locally — viewer, rule notice, bulk approval, edit validation and
/// snackbar undo — without overflowing a narrow phone.
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

  Future<void> pumpReview(WidgetTester tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const MaterialApp(home: ReviewScreen()));
    await tester.pumpAndSettle();
  }

  testWidgets('sample cards show the rule match and bulk approval',
      (tester) async {
    await pumpReview(tester);
    expect(
        find.text(
            'SAMPLE — FICTIONAL COMPANY · sign in to see your books'),
        findsOneWidget);
    expect(find.text('Screwfix'), findsOneWidget);
    expect(find.textContaining('Matches your Autopilot rule for Screwfix'),
        findsOneWidget);
    expect(find.text('Approve all 1 rule matches'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('thumbnail opens the viewer with the crop toggle',
      (tester) async {
    await pumpReview(tester);
    await tester
        .tap(find.byType(ProposalThumbnail).first);
    await tester.pumpAndSettle();
    expect(find.text('Original'), findsOneWidget);
    expect(find.text('Crop'), findsOneWidget);
    await tester.tap(find.text('Crop'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Cropped by code'), findsOneWidget);
    await tester.tap(find.text('Close'));
    await tester.pumpAndSettle();
    expect(find.text('Screwfix'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('bulk approval confirms then undoes', (tester) async {
    await pumpReview(tester);
    await tester.tap(find.text('Approve all 1 rule matches'));
    await tester.pumpAndSettle();
    expect(find.text('Approve all 1 rule matches?'), findsOneWidget);
    await tester.tap(find.text('Approve 1'));
    await tester.pumpAndSettle();
    expect(find.text('Screwfix'), findsNothing);
    expect(find.textContaining('Approved 1 of 1 rule matches'),
        findsOneWidget);
    await tester.tap(find.text('Undo'));
    await tester.pumpAndSettle();
    expect(find.text('Screwfix'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('edit sheet validates and blocks a bad total',
      (tester) async {
    await pumpReview(tester);
    final edit = find.byKey(const ValueKey('review-edit-screwfix-001'));
    await tester.ensureVisible(edit);
    await tester.pumpAndSettle();
    await tester.tap(edit);
    await tester.pumpAndSettle();
    expect(find.text('Edit proposal'), findsOneWidget);
    expect(find.text('VAT number'), findsOneWidget);
    // Break the total: net + VAT no longer equals gross.
    await tester.enterText(find.byWidgetPredicate(
        (w) => w is TextField && w.controller?.text == '38.47'), '38.00');
    await tester.pumpAndSettle();
    expect(find.textContaining("Can't save yet"), findsOneWidget);
    final save = tester.widget<FilledButton>(find.ancestor(
        of: find.text('Save & approve'),
        matching: find.byType(FilledButton)));
    expect(save.onPressed, isNull);
    expect(tester.takeException(), isNull);
  });

  testWidgets('approve then undo restores the sample card',
      (tester) async {
    await pumpReview(tester);
    final approve = find.byKey(const ValueKey('review-approve-screwfix-001'));
    await tester.ensureVisible(approve);
    await tester.pumpAndSettle();
    await tester.tap(approve);
    await tester.pumpAndSettle();
    expect(find.text('Screwfix'), findsNothing);
    await tester.tap(find.text('Undo'));
    await tester.pumpAndSettle();
    expect(find.text('Screwfix'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
