import 'package:flutter_test/flutter_test.dart';

import 'package:accnomos_mobile/services/proposal_editing.dart';

void main() {
  group('money parsing', () {
    test('parses pounds to pence', () {
      expect(parsePoundsToPence('38.47'), 3847);
      expect(parsePoundsToPence('£32.06'), 3206);
      expect(parsePoundsToPence(' 7 '), 700);
      expect(parsePoundsToPence('1,212.40'), 121240);
    });

    test('rejects non-amounts', () {
      expect(parsePoundsToPence(''), isNull);
      expect(parsePoundsToPence('n/a'), isNull);
      expect(parsePoundsToPence('-3'), isNull);
    });
  });

  group('totals check', () {
    test('net + VAT = gross passes', () {
      expect(
        totalsDiscrepancy(netPence: 3206, vatPence: 641, grossPence: 3847),
        isNull,
      );
    });

    test('mismatch names the gap', () {
      final message = totalsDiscrepancy(
        netPence: 3206,
        vatPence: 641,
        grossPence: 3800,
      );
      expect(message, contains('£38.47'));
      expect(message, contains('£38.00'));
    });
  });

  group('VAT code check', () {
    test('S at 20% passes', () {
      expect(
        vatRateDiscrepancy(code: 'S', netPence: 3206, vatPence: 641),
        isNull,
      );
    });

    test('R at 5% passes', () {
      expect(
        vatRateDiscrepancy(code: 'R', netPence: 20000, vatPence: 1000),
        isNull,
      );
    });

    test('zero-rated codes need zero VAT', () {
      for (final code in ['Z', 'E', 'O', 'N']) {
        expect(
          vatRateDiscrepancy(code: code, netPence: 5000, vatPence: 0),
          isNull,
          reason: code,
        );
      }
      expect(
        vatRateDiscrepancy(code: 'Z', netPence: 5000, vatPence: 1000),
        isNotNull,
      );
    });

    test('wrong rate is flagged', () {
      expect(
        vatRateDiscrepancy(code: 'S', netPence: 10000, vatPence: 500),
        contains('code S'),
      );
    });
  });

  group('VRN format', () {
    test('accepts 9 digits with GB prefix and spaces', () {
      expect(isValidVrn('123456789'), isTrue);
      expect(isValidVrn('GB 123 4567 89'), isTrue);
      expect(isValidVrn(''), isFalse);
      expect(isValidVrn('12345678'), isFalse);
      expect(isValidVrn('1234567890'), isFalse);
      expect(isValidVrn('GB1234567A'), isFalse);
    });

    test('empty VRN has no error (unset)', () {
      expect(vrnError(''), isNull);
      expect(vrnError('123'), isNotNull);
      expect(vrnError('123456789'), isNull);
    });
  });

  group('buildEdits', () {
    test('only changed runtime fields are sent', () {
      final edits = buildEdits(
        initialSupplier: 'Screwfix',
        currentSupplier: 'Screwfix Ltd',
        initialDateIso: '2026-10-21',
        currentDateIso: '2026-10-21',
        dateTouched: false,
        initialNet: 32.06,
        currentNet: 32.06,
        initialVat: 6.41,
        currentVat: 6.41,
        initialGross: 38.47,
        currentGross: 38.47,
        initialCategory: 'Materials',
        currentCategory: 'Materials',
      );
      expect(edits, {'supplier_name': 'Screwfix Ltd'});
    });

    test('untouched date is never sent', () {
      final edits = buildEdits(
        initialSupplier: 'Screwfix',
        currentSupplier: 'Screwfix',
        initialDateIso: null,
        currentDateIso: '2026-10-21',
        dateTouched: false,
        initialNet: null,
        currentNet: null,
        initialVat: null,
        currentVat: null,
        initialGross: null,
        currentGross: null,
        initialCategory: 'Materials',
        currentCategory: 'Materials',
      );
      expect(edits, isEmpty);
    });
  });

  group('proposal dates', () {
    test('round-trips card display dates', () {
      final date = tryParseProposalDate('21 Oct 2026');
      expect(date, DateTime(2026, 10, 21));
      expect(formatIsoDate(date!), '2026-10-21');
      expect(formatDisplayDate(date), '21 Oct 2026');
    });

    test('rejects unknown text', () {
      expect(tryParseProposalDate('Unknown date'), isNull);
      expect(tryParseProposalDate(''), isNull);
    });
  });
}
