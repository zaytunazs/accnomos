import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:accnomos_mobile/models/storage.dart';
import 'package:accnomos_mobile/screens/storage_card.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';

/// Files › storage on Android: the read-only overview from `GET /files/overview`
/// and "Back up now" (`POST /backups`), at 360 dp.
void main() {
  late List<http.Request> requested;
  int backupCode = 200;

  final overview = {
    'total_files': 42,
    'total_bytes': 3 * 1024 * 1024,
    'folders': [
      {'folder': '01 Receipts', 'files': 30, 'bytes': 2 * 1024 * 1024},
      {'folder': '_System', 'files': 12, 'bytes': 1024 * 1024},
    ],
    'years': [
      {
        'year': '2026-27',
        'files': 20,
        'bytes': 1024 * 1024,
        'archived_files': 0,
      },
      {'year': '2025-26', 'files': 10, 'bytes': 2048, 'archived_files': 10},
    ],
    'largest': <Object>[],
    'duplicates': [
      {'hash': 'sha256:ab', 'size': 1500, 'files': <Object>[]},
    ],
    'duplicate_bytes': 1500,
    'truncated': false,
  };

  RuntimeClient client() => RuntimeClient(
    AppSettings(runtimeUrl: 'http://reader'),
    books: BooksAuth(
      graphToken: 'tok',
      accountKind: 'personal',
      user: 'sam@example.co.uk',
    ),
    httpClient: MockClient((request) async {
      requested.add(request);
      if (request.method == 'POST' && request.url.path == '/backups') {
        if (backupCode != 200) {
          return http.Response(
            json.encode({
              'detail': 'Your _System folder is bigger than one backup holds',
            }),
            backupCode,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.Response(
          json.encode({
            'backup': {
              'path': 'Backups/accnomos-backup-2026-10-28.zip',
              'name': 'accnomos-backup-2026-10-28.zip',
              'size': 2048,
              'files': 12,
            },
            'retired': ['Backups/accnomos-backup-2025-10-01.zip'],
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }
      return http.Response(
        json.encode(overview),
        200,
        headers: {'content-type': 'application/json'},
      );
    }),
  );

  setUp(() {
    requested = [];
    backupCode = 200;
  });

  Future<void> narrow(WidgetTester tester) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
  }

  Widget host() => MaterialApp(
    home: Scaffold(
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [StorageCard(clientFor: () async => client())],
      ),
    ),
  );

  test('the overview parses folders, years and duplicate sets', () {
    final o = StorageOverview.fromJson(overview);
    expect(o.totalFiles, 42);
    expect(o.folders.first.name, '01 Receipts');
    expect(o.years.map((y) => y.name), ['2026-27', '2025-26']);
    expect(o.duplicateSets, 1);
    expect(sizeLabel(1500), '1 KB');
    expect(sizeLabel(3 * 1024 * 1024), '3.0 MB');
  });

  testWidgets(
    'shows the totals, folders, years and duplicates at 360 dp, reading only',
    (tester) async {
      await narrow(tester);
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('storage-total')), findsOneWidget);
      expect(find.text('42 files · 3.0 MB'), findsOneWidget);
      expect(find.text('01 Receipts'), findsOneWidget);
      expect(find.text('2025-26'), findsOneWidget);
      expect(find.textContaining('1 set of duplicates'), findsOneWidget);
      expect(tester.takeException(), isNull); // no overflow at 360 dp
      expect(requested.map((r) => '${r.method} ${r.url.path}'), [
        'GET /files/overview',
      ]);
      expect(requested.single.headers['X-Graph-Token'], 'tok');
    },
  );

  testWidgets('Back up now posts once and says where the backup went', (
    tester,
  ) async {
    await narrow(tester);
    await tester.pumpWidget(host());
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Back up now'));
    await tester.pumpAndSettle();
    expect(requested.where((r) => r.method == 'POST').map((r) => r.url.path), [
      '/backups',
    ]);
    expect(
      requested.firstWhere((r) => r.method == 'POST').headers['X-User'],
      'sam@example.co.uk',
    );
    expect(
      find.text(
        'Backed up 12 files to Backups/accnomos-backup-2026-10-28.zip. 1 older backup moved to _Trash.',
      ),
      findsOneWidget,
    );
    expect(
      requested.last.url.path,
      '/files/overview',
    ); // the totals are read again
  });

  testWidgets('a refused backup shows the runtime sentence', (tester) async {
    await narrow(tester);
    backupCode = 413;
    await tester.pumpWidget(host());
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Back up now'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Could not back up'), findsOneWidget);
    expect(find.textContaining('bigger than one backup holds'), findsOneWidget);
  });
}
