import 'package:flutter_test/flutter_test.dart';

import 'package:accnomos_mobile/models/proposal.dart';
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

  group('strict amounts', () {
    test('rejects three decimals and exponents', () {
      expect(parsePoundsToPence('12.345'), isNull);
      expect(parsePoundsToPence('1e3'), isNull);
      expect(parsePoundsToPence('.5'), isNull);
      expect(parsePoundsToPence('32.06'), 3206);
    });
  });

  group('VAT tolerance grows with the lines', () {
    test('2p plus one per line passes', () {
      expect(
        vatRateDiscrepancy(
            code: 'S', netPence: 10000, vatPence: 2003, linesCount: 1),
        isNull,
      );
      expect(
        vatRateDiscrepancy(
            code: 'S', netPence: 10000, vatPence: 2004, linesCount: 1),
        isNotNull,
      );
    });
  });

  group('validateEditForm', () {
    List<EditFieldProblem> valid() => validateEditForm(
          supplier: 'Screwfix',
          dateIso: '2026-10-21',
          netText: '32.06',
          vatText: '6.41',
          grossText: '38.47',
          category: 'Materials',
          vrnText: 'GB 232 5551 12',
          initialVrn: 'GB 232 5551 12',
          vatCode: 'S',
          linesCount: 1,
          now: DateTime(2026, 10, 27),
        );

    test('a correct form has no problems', () {
      expect(valid(), isEmpty);
    });

    test('a future date is blocked', () {
      final problems = validateEditForm(
        supplier: 'Screwfix',
        dateIso: '2026-10-28',
        netText: '32.06',
        vatText: '6.41',
        grossText: '38.47',
        category: 'Materials',
        vrnText: '',
        initialVrn: null,
        vatCode: 'S',
        linesCount: 1,
        now: DateTime(2026, 10, 27),
      );
      expect(problems.single.field, 'date');
      expect(problems.single.message, contains('in the future'));
    });

    test('a changed VAT number cannot be saved', () {
      final problems = validateEditForm(
        supplier: 'Screwfix',
        dateIso: '2026-10-21',
        netText: '32.06',
        vatText: '6.41',
        grossText: '38.47',
        category: 'Materials',
        vrnText: 'GB999999999',
        initialVrn: 'GB 232 5551 12',
        vatCode: 'S',
        linesCount: 1,
        now: DateTime(2026, 10, 27),
      );
      expect(problems.single.field, 'vrn');
      expect(problems.single.message, contains('keeps it as read'));
    });

    test('a malformed VAT number is flagged', () {
      final form = valid();
      expect(form, isEmpty);
      final problems = validateEditForm(
        supplier: 'Screwfix',
        dateIso: '2026-10-21',
        netText: '32.06',
        vatText: '6.41',
        grossText: '38.47',
        category: 'Materials',
        vrnText: '123',
        initialVrn: null,
        vatCode: 'S',
        linesCount: 1,
        now: DateTime(2026, 10, 27),
      );
      expect(problems.single.field, 'vrn');
    });
  });

  group('verifier view', () {
    test('agreement names the model and the passes', () {
      final proposal = Proposal.fromRuntime({
        'extracted': {
          'supplier_name': 'Screwfix',
          'gross_total': 38.47,
          'net_total': 32.06,
          'vat_total': 6.41,
        },
        'checks': [
          {'code': 'ARITH_TOTALS', 'ok': true, 'message': 'Totals add up'},
        ],
        'status': 'proposed',
        'model': 'local:glimmer',
        'verification': {
          'agree_all': true,
          'model': 'meta:muse-spark',
          'fields': {
            'supplier_name': {
              'extractor': 'Screwfix',
              'verifier': 'Screwfix',
              'agree': true,
            },
          },
        },
      });
      expect(proposal.verifierTone, VerifierTone.agree);
      expect(proposal.verifierNote, contains('all 1 fields match'));
      expect(proposal.verifierNote, contains('Muse Spark'));
      expect(proposal.failedChecks, isEmpty);
      expect(proposal.checksOk, isTrue);
    });

    test('failed checks stay plain English without the verifier code', () {
      final proposal = Proposal.fromRuntime({
        'extracted': {'supplier_name': 'Screwfix', 'gross_total': 38.47},
        'checks': [
          {'code': 'DUPLICATE', 'ok': false, 'message': 'Looks like a duplicate'},
          {
            'code': 'VERIFIER_AGREES',
            'ok': false,
            'message': 'Second reading differs: Date',
          },
        ],
        'status': 'needs_a_look',
        'reasons': ['DUPLICATE: Looks like a duplicate'],
        'verification': {
          'agree_all': false,
          'model': 'meta:muse-spark',
          'fields': {
            'date': {
              'extractor': '2026-11-02',
              'verifier': '2026-10-02',
              'agree': false,
            },
          },
        },
      });
      expect(proposal.failedChecks, hasLength(1));
      expect(proposal.failedChecks.single.text, 'Looks like a duplicate');
      expect(proposal.checksOk, isFalse);
      expect(proposal.reason, 'Looks like a duplicate');
      expect(proposal.verifierTone, VerifierTone.differ);
      expect(proposal.verifierDiffs, hasLength(1));
      expect(proposal.verifierDiffs.single.key, 'date');
      expect(proposal.verifierDiffs.single.field, 'Date');
    });

    test('no verification stays honest', () {
      final proposal = Proposal.fromRuntime({
        'extracted': {'supplier_name': 'Screwfix'},
        'checks': [],
        'status': 'proposed',
      });
      expect(proposal.verifierTone, VerifierTone.none);
      expect(proposal.verifierNote, contains('not run'));
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

  group('supplier VAT question', () {
    Map<String, dynamic> wire(bool ok) => {
          'status': ok ? 'proposed' : 'needs_a_look',
          'extracted': {'supplier_name': 'Hargreaves & Sons Ironmongery', 'gross_total': 368.5},
          'checks': [
            {
              'code': supplierVatUnknown,
              'ok': ok,
              'severity': 'fail',
              'message': 'Is Hargreaves & Sons Ironmongery VAT-registered? '
                  'Over £250 they should give a VAT invoice',
            },
          ],
        };

    test('a failed SUPPLIER_VAT_UNKNOWN offers the tick; its message is the question', () {
      final p = Proposal.fromBooksJson(wire(false));
      expect(p.asksVatStatus, isTrue);
      expect(p.failedChecks.single.text, startsWith('Is Hargreaves & Sons Ironmongery VAT-registered?'));
      expect(p.copyWith(category: 'Materials').asksVatStatus, isTrue);
    });

    test('no question, no tick', () {
      expect(Proposal.fromBooksJson(wire(true)).asksVatStatus, isFalse);
      expect(Proposal.fromBooksJson({'extracted': <String, dynamic>{}}).asksVatStatus, isFalse);
    });
  });
}
