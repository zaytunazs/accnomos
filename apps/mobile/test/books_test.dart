import 'package:flutter_test/flutter_test.dart';

import 'package:accnomos_mobile/services/books.dart';

void main() {
  test('gbp formats pence as pounds', () {
    expect(gbp(1234), '£12.34');
    expect(gbp(0), '£0.00');
    expect(gbp(-50), '−£0.50');
  });

  test('ukDate renders day month year', () {
    expect(ukDate('2026-10-27'), '27 Oct 2026');
    expect(ukDate(''), '—');
  });

  test('isoDate pads month and day', () {
    expect(isoDate(DateTime(2026, 4, 6)), '2026-04-06');
  });

  test('currentQuarter picks the quarter holding today', () {
    final summary = {
      'quarters': [
        {
          'period': 'Q1',
          'start': '2026-04-06',
          'end': '2026-07-05',
          'miles': 100,
          'allowance_pence': 4500,
          'unclaimed_pence': 4500,
        },
        {
          'period': 'Q2',
          'start': '2026-07-06',
          'end': '2026-10-05',
          'miles': 10,
          'allowance_pence': 450,
          'unclaimed_pence': 0,
        },
      ],
    };
    expect(
        currentQuarter(summary, DateTime(2026, 5, 1))?['period'],
        'Q1');
    expect(
        currentQuarter(summary, DateTime(2026, 9, 1))?['period'],
        'Q2');
    expect(
        currentQuarter(summary, DateTime(2027, 1, 1)), isNull);
  });
}
