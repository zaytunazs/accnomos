import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:accnomos_mobile/models/proposal.dart';
import 'package:accnomos_mobile/screens/capture_screen.dart';
import 'package:accnomos_mobile/services/capture_queue.dart';
import 'package:accnomos_mobile/services/image_prep.dart';
import 'package:accnomos_mobile/widgets/crop_editor.dart';

const _msal = MethodChannel('msal_auth');

/// A real 12×12 PNG so the preview has something to decode.
Uint8List _png() {
  final rgba = List<int>.filled(12 * 12 * 4, 200);
  return PngEncoder.encodeRgba(Uint8List.fromList(rgba), 12, 12);
}

void main() {
  setUp(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_msal, (call) async {
      throw PlatformException(
          code: 'NO_CURRENT_ACCOUNT', message: 'no account');
    });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_msal, null);
  });

  group('capture queue states', () {
    Future<void> pumpQueue(WidgetTester tester) async {
      SharedPreferences.setMockInitialValues({
        CaptureQueueStore.key: json.encode([
          CaptureItem(path: '/tmp/a.jpg', ext: '.jpg').toJson(),
          CaptureItem(
              path: '/tmp/b.jpg',
              ext: '.jpg',
              status: CaptureStatus.failed,
              error: 'Upload failed (status 500).').toJson(),
          CaptureItem(
              path: '/tmp/c.jpg',
              ext: '.jpg',
              status: CaptureStatus.uploaded,
              inboxName: 'receipt-20261027120000-1.jpg').toJson(),
        ]),
      });
      await tester.pumpWidget(
          const MaterialApp(home: CaptureScreen()));
      await tester.pumpAndSettle();
    }

    testWidgets('queued, failed and uploaded rows all show', (tester) async {
      await pumpQueue(tester);
      expect(find.text('Queued'), findsOneWidget);
      expect(find.text('Upload failed (status 500).'), findsOneWidget);
      expect(find.text('receipt-20261027120000-1.jpg'), findsOneWidget);
      // The failed row offers a retry; the photo rows offer a preview.
      expect(find.byTooltip('Retry'), findsOneWidget);
      expect(find.byTooltip('Preview and crop'), findsNWidgets(3));
      expect(tester.takeException(), isNull);
    });

    testWidgets('360 dp layout holds with a full queue', (tester) async {
      tester.view.physicalSize = const Size(360, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await pumpQueue(tester);
      expect(find.text('Take a photo'), findsOneWidget);
      expect(find.text('Choose from gallery'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('crop editor', () {
    Widget shell(CropEditor editor) => MaterialApp(
          home: Scaffold(
            body: SizedBox(
                width: 300, height: 500, child: editor),
          ),
        );

    testWidgets('dragging a corner crops, Rotate turns', (tester) async {
      var quarters = -1;
      CropRect? crop;
      await tester.pumpWidget(shell(CropEditor(
        bytes: _png(),
        onChanged: (q, c) {
          quarters = q;
          crop = c;
        },
      )));
      await tester.pumpAndSettle();

      await tester.drag(
          find.byKey(const ValueKey('crop-handle-topLeft')),
          const Offset(30, 30));
      await tester.pump();
      expect(crop, isNotNull);
      expect(crop!.left, greaterThan(0));
      expect(crop!.top, greaterThan(0));

      await tester.tap(find.text('Rotate'));
      await tester.pump();
      expect(quarters, 1);

      await tester.tap(find.text('Full frame'));
      await tester.pump();
      expect(crop, isNull);
      expect(tester.takeException(), isNull);
    });

    testWidgets('SAM note shows under the preview', (tester) async {
      await tester.pumpWidget(shell(CropEditor(bytes: _png())));
      await tester.pumpAndSettle();
      expect(find.textContaining('SAM'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('360 dp editor holds', (tester) async {
      tester.view.physicalSize = const Size(360, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: CropEditor(bytes: _png())),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Rotate'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('runtime crop note', () {
    test('Proposal keeps crop.note for the card', () {
      final proposal = Proposal.fromRuntime({
        'extracted': {'supplier_name': 'Screwfix', 'gross_total': 10.0},
        'status': 'proposed',
        'crop': {'method': 'sam', 'note': 'SAM cut the background'},
      });
      expect(proposal.cropNote, 'SAM cut the background');
      expect(
          Proposal.fromRuntime({'extracted': {}}).cropNote, isNull);
    });
  });
}
