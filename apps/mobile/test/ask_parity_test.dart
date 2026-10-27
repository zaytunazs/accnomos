import 'package:accnomos_mobile/models/ask_answer.dart';
import 'package:accnomos_mobile/models/ask_suggestions.dart';
import 'package:accnomos_mobile/models/day_plan.dart';
import 'package:flutter_test/flutter_test.dart';

AskAnswer answerJson(Map<String, dynamic> extra) => AskAnswer.fromJson({
      'answer_md': 'Your Q3 bill is £2,140.',
      'key_numbers': [],
      'citations': [],
      'suggested_actions': [],
      'confidence': 'high',
      'model': 'Muse Spark',
      'period': {'start': '2026-07-01', 'end': '2026-09-30'},
      'fallback_reason': null,
      ...extra,
    });

void main() {
  group('Clarification', () {
    test('parses question, candidates and ref', () {
      final a = answerJson({
        'clarification': {
          'kind': 'create_invoice',
          'field': 'customer',
          'question_md': 'Which customer did you mean?',
          'candidates': ['Hartley Kitchens', 'Howdens'],
          'ref': 'Hartley',
        },
      });
      expect(a.clarification, isNotNull);
      expect(a.clarification!.questionMd, 'Which customer did you mean?');
      expect(a.clarification!.candidates,
          ['Hartley Kitchens', 'Howdens']);
      expect(a.clarification!.ref, 'Hartley');
    });

    test('is null when the runtime sent none', () {
      expect(answerJson({}).clarification, isNull);
    });

    test('withPicked swaps the user words for the candidate', () {
      final c = Clarification(
        kind: 'create_invoice',
        field: 'customer',
        questionMd: 'Which customer did you mean?',
        candidates: ['Hartley Kitchens'],
        ref: 'Hartley',
      );
      expect(
        withPicked('Invoice Hartley for the kitchen job', c, 'Hartley Kitchens'),
        'Invoice Hartley Kitchens for the kitchen job',
      );
    });

    test('withPicked appends when the ref is missing', () {
      final c = Clarification(
        kind: 'create_invoice',
        field: 'customer',
        questionMd: 'Which customer did you mean?',
      );
      expect(
        withPicked('Invoice them for the job', c, 'Hartley Kitchens'),
        'Invoice them for the job (Hartley Kitchens)',
      );
    });
  });

  group('workbookSheet', () {
    test('VAT wins over the ledger', () {
      final a = answerJson({
        'citations': ['06 VAT returns/2026-Q3/return.json', 'Books.xlsx'],
      });
      expect(workbookSheet(a), 'VAT');
    });

    test('names the Books.xlsx sheet for other answers', () {
      final a = answerJson({
        'citations': ['04 Bank statements/lloyds.csv', 'Books.xlsx'],
      });
      expect(workbookSheet(a), 'Bank');
    });

    test('falls back to Summary', () {
      expect(workbookSheet(answerJson({})), 'Summary');
    });
  });

  group('suggestedAskQuestions', () {
    Map<String, dynamic> dashboard() => {
          'cash': {'balance_pence': 1248000, 'as_of': '2026-10-26'},
          'owed_to_you': {'total_pence': 50000, 'documents': 2},
          'owed_by_you': {'total_pence': 30000, 'documents': 1},
          'vat': {
            'current': {'label': 'Q3', 'box5': '2140.00'},
            'due': {'label': 'Q3', 'box5': '2140.00'},
          },
          'attention': {
            'proposed': 1,
            'needs_a_look': 0,
            'unmatched_bank_lines': 3,
          },
        };

    test('mirrors the web wording', () {
      expect(suggestedAskQuestions(dashboard()), [
        'Why is my VAT £2,140.00 for Q3?',
        'Who owes me the most?',
        'What do I owe and when is it due?',
        'Which bank lines still need matching?',
      ]);
    });

    test('names the Box 5 direction when the filed return differs', () {
      final d = dashboard();
      (d['vat'] as Map)['due'] = {'label': 'Q3', 'box5': '2760.00'};
      expect(suggestedAskQuestions(d).first,
          'Why is Box 5 higher this quarter?');
    });

    test('falls back when the dashboard cannot be read', () {
      expect(suggestedAskQuestions(null), askFallbackQuestions);
      expect(suggestedAskQuestions({}), askFallbackQuestions);
      expect(askFallbackQuestions, [
        'Why is my VAT different from last quarter?',
        'Who owes me the most?',
        'What needs my attention?',
      ]);
    });

    test('keeps at most four', () {
      final d = dashboard();
      expect(suggestedAskQuestions(d).length, lessThanOrEqualTo(4));
    });
  });

  group('DayPlan', () {
    test('parses the timeline and counts fresh items', () {
      final plan = DayPlan.fromJson({
        'date': '2026-10-29',
        'plan': [
          {
            'kind': 'visit',
            'start': '2026-10-29T09:00:00+01:00',
            'end': '2026-10-29T11:00:00+01:00',
            'job_id': 'j1',
            'title': 'Hartley kitchen',
            'location': 'Elm Road',
          },
          {
            'kind': 'existing',
            'start': '2026-10-29T12:00:00+01:00',
            'end': '2026-10-29T13:00:00+01:00',
            'job_id': null,
            'title': 'Lunch with Sam',
            'location': null,
          },
        ],
        'rationale_md': 'Visit first, then lunch.',
        'warnings': ['Rain expected.'],
        'plan_hash': 'abc',
        'model': 'Muse Spark',
        'fallback_reason': null,
      });
      expect(plan.items.length, 2);
      expect(plan.fresh.length, 1);
      expect(plan.fresh.first.title, 'Hartley kitchen');
      expect(plan.warnings, ['Rain expected.']);
    });

    test('AppliedPlan counts created events', () {
      final applied = AppliedPlan.fromJson({
        'date': '2026-10-29',
        'plan_hash': 'abc',
        'event_ids': ['e1'],
        'created': [
          {'title': 'Hartley kitchen', 'start': 'x', 'event_id': 'e1', 'reused': false},
          {'title': 'Old', 'start': 'y', 'event_id': 'e0', 'reused': true},
        ],
        'already_applied': false,
        'mileage_proposals': [],
      });
      expect(applied.created, ['Hartley kitchen']);
      expect(applied.alreadyApplied, isFalse);
    });
  });
}
