import 'dart:convert';

import 'package:accnomos_mobile/models/scan_job.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:accnomos_mobile/widgets/scan_progress.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

/// Background scans on the phone (`services/runtime/app/scan_jobs.py`): the
/// client's wire shapes match the web's `runtime.startScan/scanJob/
/// confirmScan`, and [ScanJobCard] shows per-file progress, the AI's guess
/// with its confidence, and sends the user's type on Confirm.
Map<String, dynamic> fileJson(String name, String stage,
        {String? guess, double progress = 0.5, String? proposal}) =>
    {
      'name': name,
      'path': '00 Inbox/$name',
      'stage': stage,
      'stage_label': {
        'reading': 'Reading',
        'confirm': 'Confirm the type',
        'checking': 'Checking',
        'ready': 'Ready to review',
      }[stage],
      'progress': progress,
      'guess': guess == null
          ? null
          : {'kind': guess, 'confidence': 0.87, 'reason': 'Fake', 'by': 'ai'},
      'kind': null,
      'route': proposal == null ? null : 'review',
      'proposal_id': proposal,
      'message': null,
    };

Map<String, dynamic> jobJson(String status, List<Map<String, dynamic>> files,
        {double progress = 0.5}) =>
    {
      'id': 'ab' * 16,
      'source': 'phone',
      'status': status,
      'progress': progress,
      'interrupted': false,
      'files': files,
      'counts': {},
    };

void main() {
  group('RuntimeClient scan jobs', () {
    final requests = <http.Request>[];
    RuntimeClient client(Map<String, dynamic> answer) => RuntimeClient(
          AppSettings(runtimeUrl: 'http://reader', vatStagger: 2),
          books: BooksAuth(
              graphToken: 'tok', accountKind: 'personal', user: 'me@x.uk'),
          httpClient: MockClient((r) async {
            requests.add(r);
            return http.Response(json.encode(answer), 200,
                headers: {'content-type': 'application/json'});
          }),
        );

    setUp(requests.clear);

    test('start posts the uploaded names and answers with the job', () async {
      final job = await client(jobJson('working', [
        fileJson('receipt-1.jpg', 'uploaded', progress: 0.1),
      ])).startScanJob(names: ['receipt-1.jpg']);
      final r = requests.single;
      expect(r.method, 'POST');
      expect(r.url.path, '/books/scan/jobs');
      expect(r.url.queryParameters['stagger'], '2');
      expect(json.decode(r.body),
          {'names': ['receipt-1.jpg'], 'source': 'phone'});
      expect(job.working, isTrue);
      expect(job.files.single.progress, 0.1);
    });

    test('confirm sends each file with its type', () async {
      final job = await client(jobJson('working', [
        fileJson('a.jpg', 'checking'),
      ])).confirmScanJob('ab' * 16, {'a.jpg': 'payslip'});
      final r = requests.single;
      expect(r.url.path, '/books/scan/jobs/${'ab' * 16}/confirm');
      expect(json.decode(r.body), {
        'files': [
          {'name': 'a.jpg', 'kind': 'payslip'},
        ],
      });
      expect(r.headers['X-User'], 'me@x.uk');
      expect(job.files.single.stage, 'checking');
    });
  });

  group('ScanJob', () {
    test('headline and guesses read like the web', () {
      final job = ScanJob.fromJson(jobJson('waiting', [
        fileJson('a.jpg', 'confirm', guess: 'receipt'),
        fileJson('b.pdf', 'confirm', guess: 'pizza'),
      ]));
      expect(job.headline, '2 to confirm: what kind of document is it?');
      expect(job.files.first.guess!.label, 'Receipt');
      expect(job.files.first.guess!.percent, 87);
      expect(job.files.last.guess!.kind, 'other'); // unknown kinds fall back
      final done = ScanJob.fromJson(jobJson('done', [
        fileJson('a.jpg', 'ready', progress: 1, proposal: 'p1'),
      ], progress: 1));
      expect(done.headline, 'Done · 1 ready to review');
      expect(done.cards, 1);
    });
  });

  testWidgets('the card shows progress and the guess, and Confirm sends it',
      (tester) async {
    final confirmed = <Map<String, String>>[];
    var loads = 0;
    var filed = 0;
    final waiting = ScanJob.fromJson(jobJson('waiting', [
      fileJson('a.jpg', 'confirm', guess: 'receipt'),
    ]));
    final ready = ScanJob.fromJson(jobJson('done', [
      fileJson('a.jpg', 'ready', progress: 1, proposal: 'p1'),
    ], progress: 1));
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: ScanJobCard(
          job: ScanJob.fromJson(jobJson('working', [
            fileJson('a.jpg', 'reading', progress: 0.3),
          ], progress: 0.3)),
          pollEvery: const Duration(milliseconds: 100),
          load: (_) async {
            loads++;
            return waiting;
          },
          confirm: (_, kinds) async {
            confirmed.add(kinds);
            return ready;
          },
          onFiled: (n) => filed += n,
        ),
      ),
    ));
    expect(find.text('Reading 1 file…'), findsOneWidget);
    expect(find.text('Reading'), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 150)); // one poll
    await tester.pump();
    expect(loads, 1);
    expect(find.textContaining('Looks like a receipt (87% sure)'), findsOneWidget);
    expect(find.text('Confirm the type'), findsOneWidget);

    await tester.tap(find.text('Receipt'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Payslip').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Confirm'));
    await tester.pump();
    expect(confirmed, [
      {'a.jpg': 'payslip'},
    ]);
    expect(find.text('Done · 1 ready to review'), findsOneWidget);
    expect(filed, 1);

    await tester.pump(const Duration(seconds: 20)); // done: no more polling
    expect(loads, 1);
  });
}
