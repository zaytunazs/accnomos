import 'package:flutter_test/flutter_test.dart';

import 'package:accnomos_mobile/services/review_rules.dart';

ReviewRule screwfixRule() => ReviewRule(
      supplierKey: 'screwfix',
      supplierName: 'Screwfix',
      category: 'Tools & small equipment',
      account: '5100 Tools & small equipment',
      vatCode: 'S',
      side: 'purchase',
      typicalGrossPence: 3847,
      vrn: 'GB232555112',
    );

ProposalRuleView screwfixProposal() => const ProposalRuleView(
      supplierName: 'Screwfix',
      docType: 'receipt',
      mileageClaim: false,
      statusProposed: true,
      checksOk: true,
      supplierVrn: 'GB 232 5551 12',
      vatCodes: ['S'],
      grossPence: 3847,
      categoryGuess: 'Tools & small equipment',
      expenseAccount: '5100 Tools & small equipment',
    );

void main() {
  group('supplierKey', () {
    test('strips company suffixes', () {
      expect(supplierKey('Screwfix Direct Ltd.'), 'screwfix-direct');
      expect(supplierKey('Acme Limited'), 'acme');
      expect(supplierKey('The Tesco Store'), 'tesco-store');
    });

    test('normalises punctuation', () {
      expect(supplierKey("Sainsbury's"), 'sainsburys');
      expect(supplierKey('B&Q'), 'b-and-q');
    });
  });

  group('normaliseVrn', () {
    test('adds the GB prefix to bare digits', () {
      expect(normaliseVrn('123456789'), 'GB123456789');
      expect(normaliseVrn('GB 123 4567 89'), 'GB123456789');
      expect(normaliseVrn('GB123456789012'), 'GB123456789012');
    });

    test('empty means no number printed', () {
      expect(normaliseVrn(null), isNull);
      expect(normaliseVrn(''), isNull);
      expect(normaliseVrn('VAT NO:'), isNull);
    });
  });

  group('vrnLooksValid', () {
    test('accepts the shapes the runtime accepts', () {
      expect(vrnLooksValid(''), isTrue);
      expect(vrnLooksValid('GB123456789'), isTrue);
      expect(vrnLooksValid('GB 123 4567 89'), isTrue);
      expect(vrnLooksValid('GB123456789012'), isTrue);
      expect(vrnLooksValid('XI123456789'), isTrue);
      expect(vrnLooksValid('GBGD001'), isTrue);
    });

    test('rejects short or lettered numbers', () {
      expect(vrnLooksValid('123'), isFalse);
      expect(vrnLooksValid('GB12345678'), isFalse);
      expect(vrnLooksValid('GB12345678A'), isFalse);
    });
  });

  group('matchingRule', () {
    test('matches the Screwfix sample', () {
      expect(
        matchingRule(screwfixProposal(), [screwfixRule()]),
        isNotNull,
      );
    });

    test('newest rule for the supplier wins', () {
      final old = screwfixRule();
      final newer = ReviewRule(
        supplierKey: 'screwfix',
        supplierName: 'Screwfix',
        category: 'Materials',
        account: null,
        vatCode: 'S',
        side: 'purchase',
        typicalGrossPence: 3847,
        vrn: 'GB232555112',
      );
      expect(matchingRule(screwfixProposal(), [old, newer]), newer);
    });

    test('rejects non-purchases, mileage and flagged cards', () {
      final rules = [screwfixRule()];
      expect(
        matchingRule(
          screwfixProposal().copyWith(docType: 'sales_invoice'),
          rules,
        ),
        isNull,
        reason: 'sales invoices never match',
      );
      expect(
        matchingRule(screwfixProposal().copyWith(mileageClaim: true), rules),
        isNull,
        reason: 'mileage claims never match',
      );
      expect(
        matchingRule(screwfixProposal().copyWith(statusProposed: false), rules),
        isNull,
        reason: 'needs-a-look never matches',
      );
      expect(
        matchingRule(screwfixProposal().copyWith(checksOk: false), rules),
        isNull,
        reason: 'failed checks never match',
      );
    });

    test('rejects VRN, VAT code and total mismatches', () {
      final rules = [screwfixRule()];
      expect(
        matchingRule(
          screwfixProposal().copyWith(supplierVrn: 'GB999999999'),
          rules,
        ),
        isNull,
        reason: 'VRN mismatch',
      );
      expect(
        matchingRule(screwfixProposal().copyWith(vatCodes: ['Z']), rules),
        isNull,
        reason: 'VAT code mismatch',
      );
      expect(
        matchingRule(screwfixProposal().copyWith(vatCodes: []), rules),
        isNull,
        reason: 'no VAT code never matches a coded rule',
      );
      expect(
        matchingRule(screwfixProposal().copyWith(grossPence: 2 * 3847 + 1), rules),
        isNull,
        reason: 'over twice the usual total',
      );
      expect(
        matchingRule(screwfixProposal().copyWith(grossPence: 0), rules),
        isNull,
        reason: 'zero total',
      );
    });

    test('no rule for the supplier means no match', () {
      expect(
        matchingRule(
          screwfixProposal().copyWith(supplierName: 'Travis Perkins'),
          [screwfixRule()],
        ),
        isNull,
      );
      expect(matchingRule(screwfixProposal(), []), isNull);
    });
  });

  group('ruleEdits', () {
    test('sends only what differs', () {
      expect(ruleEdits(screwfixProposal(), screwfixRule()), isNull);
      final edits = ruleEdits(
        screwfixProposal().copyWith(categoryGuess: 'Sundry'),
        screwfixRule(),
      );
      expect(edits, {'category': 'Tools & small equipment'});
    });

    test('sends the rule account when it differs', () {
      final edits = ruleEdits(
        screwfixProposal().copyWith(expenseAccount: '7500 Sundry'),
        screwfixRule(),
      );
      expect(edits, {'account': '5100 Tools & small equipment'});
    });
  });

  group('vatCodesOfJournal', () {
    test('reads the expense lines, not VAT control', () {
      final journal = [
        {'account': '5100 Tools', 'debit_pence': 3206, 'vat_code': 'S'},
        {'account': '2200 VAT control', 'debit_pence': 641, 'vat_code': 'S'},
        {'account': '1200 Bank', 'credit_pence': 3847, 'vat_code': null},
      ];
      expect(vatCodesOfJournal(journal, false), ['S']);
      expect(vatCodesOfJournal(journal, true), []);
    });
  });

  group('plainReason', () {
    test('drops the checker code, keeps the note', () {
      expect(
        plainReason('DUPLICATE: Looks like a duplicate'),
        'Looks like a duplicate',
      );
      expect(plainReason('Just a note'), 'Just a note');
    });
  });
}
