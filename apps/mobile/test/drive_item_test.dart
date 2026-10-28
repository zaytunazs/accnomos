import 'package:flutter_test/flutter_test.dart';

import 'package:accnomos_mobile/services/graph.dart';

Map<String, dynamic> folderJson() => {
      'id': 'folder-1',
      'name': '05 VAT returns',
      'folder': {'childCount': 3},
      'lastModifiedDateTime': '2026-10-21T09:30:00.000Z',
      'webUrl': 'https://example.test/folder',
    };

Map<String, dynamic> fileJson() => {
      'id': 'file-1',
      'name': 'return.json',
      'size': 12698,
      'lastModifiedDateTime': '2026-10-20T14:00:00.000Z',
      'webUrl': 'https://example.test/file',
    };

void main() {
  group('DriveItem.fromJson', () {
    test('parses a folder with its count', () {
      final item = DriveItem.fromJson(folderJson());
      expect(item.isFolder, isTrue);
      expect(item.name, '05 VAT returns');
      expect(item.childCount, 3);
      expect(item.countLabel, '3 items');
    });

    test('parses a file with size and link', () {
      final item = DriveItem.fromJson(fileJson());
      expect(item.isFolder, isFalse);
      expect(item.size, 12698);
      expect(item.webUrl, 'https://example.test/file');
    });

    test('tolerates missing facets', () {
      final item = DriveItem.fromJson({'id': 'x'});
      expect(item.name, 'Unnamed');
      expect(item.isFolder, isFalse);
      expect(item.countLabel, '');
      expect(item.dateLabel, '');
    });
  });

  group('DriveItem labels', () {
    test('counts use singular and empty forms', () {
      final one = DriveItem(
          id: 'a', name: 'A', isFolder: true, childCount: 1);
      final none = DriveItem(
          id: 'b', name: 'B', isFolder: true, childCount: 0);
      expect(one.countLabel, '1 item');
      expect(none.countLabel, 'Empty');
    });

    test('sizes use bytes, KB and MB', () {
      String sized(int bytes) => DriveItem(
          id: 'a', name: 'A', isFolder: false, size: bytes).sizeLabel;
      expect(sized(812), '812 bytes');
      expect(sized(12698), '12.4 KB');
      expect(sized(3 * 1024 * 1024), '3.0 MB');
    });

    test('dates render in UK order', () {
      final item = DriveItem.fromJson(fileJson());
      // 14:00Z on 20 Oct is the 20th or the 21st on the device's clock, depending on its time zone.
      final day = DateTime.utc(2026, 10, 20, 14).toLocal().day;
      expect(item.dateLabel, '$day Oct 2026');
    });
  });
}
