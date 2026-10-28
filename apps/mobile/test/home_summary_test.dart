import 'package:accnomos_mobile/models/home_summary.dart';
import 'package:accnomos_mobile/screens/home_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Home's summary card (parity with the web's "Your summary"): the text from
/// `GET /books/home`, who wrote it, and no overflow on a 360 dp phone.
void main() {
  const summaryJson = {
    'summary': {
      'summary_md': 'You had £5,400.00 in the bank on 24 Oct 2026. '
          'To do: 2 items waiting in Review.',
      'model': 'code',
      'fallback_reason': 'No AI is set up, so code wrote this.',
      'facts': <String, dynamic>{},
    },
  };

  test('parses the summary and says code wrote it when no AI is set up', () {
    final s = HomeSummary.fromHomeJson(summaryJson)!;
    expect(s.text, startsWith('You had £5,400.00 in the bank'));
    expect(s.byAi, isFalse);
    expect(s.byLine, contains('No AI is set up, so code wrote this.'));
  });

  test('an AI summary that passed the number check says so', () {
    const s = HomeSummary(text: 'x', model: 'muse-glimmer:30b');
    expect(s.byAi, isTrue);
    expect(s.byLine, contains('worded by your AI (muse-glimmer:30b), numbers checked by code'));
  });

  test('no summary, or an empty one, is null', () {
    expect(HomeSummary.fromHomeJson(const {}), isNull);
    expect(
        HomeSummary.fromHomeJson(const {
          'summary': {'summary_md': '  ', 'model': 'code'}
        }),
        isNull);
  });

  testWidgets('the card fits a 360 dp phone and is labelled', (tester) async {
    tester.view.physicalSize = const Size(360, 780);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: SummaryCard(summary: HomeSummary.fromHomeJson(summaryJson)!),
      ),
    ));
    expect(find.text('Your summary'), findsOneWidget);
    expect(find.textContaining('£5,400.00'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
