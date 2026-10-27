import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:accnomos_mobile/services/capture_queue.dart';
import 'package:accnomos_mobile/services/image_prep.dart';

void main() {
  group('inbox naming', () {
    test('receipt-<stamp>-<n>.<ext> in batch order', () {
      expect(inboxNameFor('20261027120000', 0, '.jpg'),
          'receipt-20261027120000-1.jpg');
      expect(inboxNameFor('20261027120000', 2, '.pdf'),
          'receipt-20261027120000-3.pdf');
    });

    test('stamp is 14 digits', () {
      expect(stampFor(DateTime(2026, 10, 27, 12, 0, 0)), '20261027120000');
    });

    test('extensions and content types', () {
      expect(extFor('/a/photo.JPEG'), '.jpg');
      expect(extFor('/a/noext'), '.jpg');
      expect(extFor('/a/doc.PDF'), '.pdf');
      expect(contentTypeFor('receipt-1.jpg'), 'image/jpeg');
      expect(contentTypeFor('receipt-1.png'), 'image/png');
      expect(contentTypeFor('receipt-1.pdf'), 'application/pdf');
    });
  });

  group('CropRect maths', () {
    test('normalised clamps and orders edges', () {
      const raw = CropRect(left: 0.8, top: 0.9, right: 0.2, bottom: 0.1);
      expect(raw.normalised(),
          const CropRect(left: 0.2, top: 0.1, right: 0.8, bottom: 0.9));
      const over = CropRect(left: -1, top: -1, right: 2, bottom: 2);
      expect(over.normalised().isFull, isTrue);
    });

    test('four quarter turns return the start', () {
      const start =
          CropRect(left: 0.1, top: 0.2, right: 0.7, bottom: 0.8);
      var rect = start;
      for (var i = 0; i < 4; i++) {
        rect = rect.quarterTurn();
      }
      expect(rect, start);
    });

    test('one quarter turn maps (l,t,r,b) to (1-b,l,1-t,r)', () {
      const start =
          CropRect(left: 0.1, top: 0.2, right: 0.7, bottom: 0.8);
      expect(start.quarterTurn(),
          const CropRect(left: 0.2, top: 0.1, right: 0.8, bottom: 0.7));
    });

    test('toPixels stays inside the image and is never empty', () {
      const rect = CropRect(left: 0.25, top: 0.25, right: 0.75, bottom: 0.5);
      final px = rect.toPixels(200, 100);
      expect((px.x, px.y, px.width, px.height), (50, 25, 100, 25));
      final tiny =
          const CropRect(left: 0.99, top: 0.99, right: 1, bottom: 1)
              .toPixels(200, 100);
      expect(tiny.width, greaterThanOrEqualTo(1));
      expect(tiny.height, greaterThanOrEqualTo(1));
      expect(tiny.x + tiny.width, lessThanOrEqualTo(200));
      expect(tiny.y + tiny.height, lessThanOrEqualTo(100));
    });

    test('json round trip', () {
      const rect =
          CropRect(left: 0.1, top: 0.2, right: 0.7, bottom: 0.8);
      expect(CropRect.fromJson(rect.toJson()), rect);
    });
  });

  group('CaptureItem', () {
    test('uploading parks back to queued after a restart', () {
      final item = CaptureItem(path: '/tmp/a.jpg', ext: '.jpg')
          .copyWith(status: CaptureStatus.uploading);
      final revived = CaptureItem.fromJson(item.toJson());
      expect(revived.status, CaptureStatus.queued);
    });

    test('edited tracks rotation and crop only', () {
      final plain = CaptureItem(path: '/tmp/a.jpg', ext: '.jpg');
      expect(plain.edited, isFalse);
      expect(plain.copyWith(rotationQuarters: 1).edited, isTrue);
      expect(plain.copyWith(crop: CropRect.full()).edited, isFalse);
      expect(
          plain
              .copyWith(
                  crop: const CropRect(
                      left: 0.1, top: 0.1, right: 0.9, bottom: 0.9))
              .edited,
          isTrue);
    });
  });

  group('CaptureQueueStore', () {
    test('save and load round trip; corrupt payload loads empty', () async {
      SharedPreferences.setMockInitialValues({});
      final items = [
        CaptureItem(path: '/tmp/a.jpg', ext: '.jpg'),
        CaptureItem(path: '/tmp/b.pdf', ext: '.pdf',
            status: CaptureStatus.failed, error: 'Nope'),
      ];
      await CaptureQueueStore.save(items);
      final loaded = await CaptureQueueStore.load();
      expect(loaded.map((i) => i.path), ['/tmp/a.jpg', '/tmp/b.pdf']);
      expect(loaded[1].status, CaptureStatus.failed);
      expect(loaded[1].error, 'Nope');

      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(CaptureQueueStore.key, 'not json{');
      expect(await CaptureQueueStore.load(), isEmpty);
    });
  });

  group('CaptureScanSummary', () {
    test('label reads "N new, M need a look"', () {
      expect(const CaptureScanSummary(fresh: 3, needALook: 0).label,
          '3 new proposals');
      expect(const CaptureScanSummary(fresh: 1, needALook: 1).label,
          '1 new proposal, 1 needs a look');
      expect(const CaptureScanSummary(fresh: 2, needALook: 3).label,
          '2 new proposals, 3 need a look');
    });
  });

  group('PngEncoder', () {
    test('round trip keeps dimensions', () {
      final rgba = List<int>.filled(8 * 6 * 4, 128);
      final png =
          PngEncoder.encodeRgba(Uint8List.fromList(rgba), 8, 6);
      expect(PngEncoder.probeDimensions(png), (8, 6));
      expect(base64.encode(png).isNotEmpty, isTrue);
    });

    test('prepared bytes rotate the frame', () async {
      final rgba = List<int>.filled(8 * 6 * 4, 200);
      final src =
          PngEncoder.encodeRgba(Uint8List.fromList(rgba), 8, 6);
      final out = await ImagePrep.preparedBytes(
        src: src,
        quarters: 1,
        crop: null,
        isPdf: false,
      );
      expect(PngEncoder.probeDimensions(out), (6, 8));
    });

    test('prepared bytes crop then turn', () async {
      final rgba = List<int>.filled(8 * 6 * 4, 200);
      final src =
          PngEncoder.encodeRgba(Uint8List.fromList(rgba), 8, 6);
      final out = await ImagePrep.preparedBytes(
        src: src,
        quarters: 1,
        crop: const CropRect(left: 0, top: 0, right: 1, bottom: 0.5),
        isPdf: false,
      );
      // 8x3 cut, turned once -> 3x8.
      expect(PngEncoder.probeDimensions(out), (3, 8));
    });

    test('untouched photos and PDFs pass through byte-identical', () async {
      final rgba = List<int>.filled(4 * 4 * 4, 10);
      final src =
          PngEncoder.encodeRgba(Uint8List.fromList(rgba), 4, 4);
      final same = await ImagePrep.preparedBytes(
        src: src,
        quarters: 0,
        crop: null,
        isPdf: false,
      );
      expect(same, src);
      final pdf = await ImagePrep.preparedBytes(
        src: src,
        quarters: 3,
        crop: const CropRect(left: 0, top: 0, right: 0.5, bottom: 0.5),
        isPdf: true,
      );
      expect(pdf, src);
    });
  });
}
