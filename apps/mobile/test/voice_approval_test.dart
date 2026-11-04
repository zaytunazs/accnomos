import 'dart:convert';

import 'package:accnomos_mobile/models/ask_answer.dart';
import 'package:accnomos_mobile/screens/notes_screen.dart';
import 'package:accnomos_mobile/services/hands_free.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:accnomos_mobile/services/voice_approval.dart';
import 'package:accnomos_mobile/widgets/action_card.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Verbal approval (services/voice_approval.dart) — the web's
/// lib/voiceApproval.ts rules — and the Notes screen.
ProposedAction card(String kind, Map<String, dynamic> preview, {String summary = 'Save this note: “Order screws”.', bool tapOnly = false}) =>
    ProposedAction({
      'id': '0' * 32,
      'kind': kind,
      'summary_md': summary,
      'preview': preview,
      'confirm_text': 'Do it',
      'created_at': '2026-11-04T09:00:00Z',
      'expires_at': '2026-11-04T09:15:00Z',
      if (tapOnly) 'tap_only': true,
      'signature': 'sig',
    });

void main() {
  test('only a whole-reply yes is a yes; silence is a no', () {
    for (final s in ['yes', 'Yes please.', 'go ahead', 'do it', 'confirm', 'approve', 'okay thanks']) {
      expect(hearReply(s), SpokenReply.yes, reason: s);
    }
    for (final s in ['no', 'cancel', 'not now', '', 'leave it']) {
      expect(hearReply(s), SpokenReply.no, reason: s);
    }
    for (final s in ['yes but change the time', 'hmm', 'what?']) {
      expect(hearReply(s), SpokenReply.unclear, reason: s);
    }
  });

  test('money and times are read as words', () {
    expect(inWords('£480.00'), 'four hundred and eighty pounds');
    expect(inWords('Friday 6 November, 10:00–11:00'), 'Friday 6 November, 10 am to 11 am');
    expect(inWords('at 15:30'), 'at 3 30 pm');
  });

  test('the read-back asks, names a clash, and says when a tap is needed', () {
    expect(cardReadBack(card('save_note', {})), endsWith('Shall I go ahead? Say yes or no.'));
    final clash = card('calendar_add_event', {
      'conflicts': [
        {'id': 'v1', 'subject': 'Site visit, Hartwell'}
      ]
    }, summary: 'Add **Call** to your calendar: Friday 6 November, 10:30–11:30. This clashes with Site visit, Hartwell, 10:00–11:00.');
    final said = cardReadBack(clash);
    expect(said, contains('This clashes with Site visit, Hartwell, 10 am to 11 am'));
    expect(said, endsWith('Add it anyway? Say yes or no.'));
    final money = cardReadBack(card('chase_invoice', {'total_pence': 48000}, summary: 'Email a reminder for INV-0007 (£480.00).', tapOnly: true));
    expect(money, contains('needs you to tap Approve'));
    expect(money, isNot(contains('Shall I go ahead')));
  });

  group('the dialogue', () {
    late List<String> spoken;
    late List<String> approvedWith;

    Future<bool> run(ProposedAction a, List<String?> replies) {
      var i = 0;
      return approveByVoice(
        action: a,
        speak: (s) async => spoken.add(s),
        listen: () async {
          if (i >= replies.length) return null;
          if (replies[i] == null) {
            i++;
            return null;
          }
          return [1, 2, 3];
        },
        transcribe: (_) async => replies[i++],
        approve: (heard) async {
          approvedWith.add(heard);
          return 'Saved your note: “Order screws”.';
        },
      );
    }

    setUp(() {
      spoken = [];
      approvedWith = [];
    });

    test('voice yes → the approve call, with what was heard', () async {
      expect(await run(card('save_note', {}), ['Yes please']), isTrue);
      expect(approvedWith, ['Yes please']);
      expect(spoken.last, contains('Saved your note'));
    });

    test('no → no call; the card is left for a tap', () async {
      expect(await run(card('save_note', {}), ['no']), isFalse);
      expect(approvedWith, isEmpty);
      expect(spoken.last, contains('left it on screen'));
    });

    test('silence → no call', () async {
      expect(await run(card('save_note', {}), [null]), isFalse);
      expect(approvedWith, isEmpty);
    });

    test('unclear twice → asked once more, then left', () async {
      expect(await run(card('save_note', {}), ['hmm', 'what']), isFalse);
      expect(approvedWith, isEmpty);
      expect(spoken.where((s) => s == askAgain), hasLength(1));
    });

    test('a card that moves money never listens for a yes', () async {
      var listened = false;
      final ok = await approveByVoice(
        action: card('pay_overtime', {}, tapOnly: true),
        speak: (s) async => spoken.add(s),
        listen: () async {
          listened = true;
          return [1];
        },
        transcribe: (_) async => 'yes',
        approve: (heard) async {
          approvedWith.add(heard);
          return 'done';
        },
      );
      expect(ok, isFalse);
      expect(listened, isFalse);
      expect(approvedWith, isEmpty);
      expect(spoken.single, contains('tap Approve'));
    });

    test('hands-free carries on after a spoken yes', () async {
      final states = <HandsFreeState>[];
      var t = 0;
      final asked = <ProposedAction>[];
      await HandsFreeLoop(
        listen: (_) async => t++ == 0 ? [1] : null,
        ask: (_) async => HandsFreeReply(transcript: 'take a note', answerMd: 'card', action: card('save_note', {})),
        speak: (s) async => spoken.add(s),
        onState: states.add,
        approve: (a) async {
          asked.add(a);
          return true;
        },
      ).run();
      expect(asked, hasLength(1));
      expect(states.where((s) => s == HandsFreeState.listening), hasLength(3)); // went on listening
    });
  });

  test('approve by voice posts via voice and what was heard', () async {
    SharedPreferences.setMockInitialValues({});
    Map<String, dynamic>? sent;
    final c = RuntimeClient(
      AppSettings(runtimeUrl: 'http://reader'),
      books: BooksAuth(graphToken: 'tok', accountKind: 'personal', user: 'sam@example.co.uk'),
      httpClient: MockClient((r) async {
        sent = json.decode(r.body) as Map<String, dynamic>;
        return http.Response('{"summary_md":"Saved","status":"done"}', 200, headers: {'content-type': 'application/json'});
      }),
    );
    await c.approveAction(card('save_note', {}), heard: 'yes please');
    expect(sent!['via'], 'voice');
    expect(sent!['heard'], 'yes please');
    await c.approveAction(card('save_note', {}));
    expect(sent!.containsKey('via'), isFalse); // a tap sends the card alone
  });

  test('the new kinds have card labels', () {
    for (final k in ['save_note', 'delete_note', 'add_todo', 'calendar_add_event', 'calendar_remove_event']) {
      expect(actionKindLabels[k], isNotNull, reason: k);
    }
  });

  testWidgets('Notes screen lists, adds and deletes after a confirm', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final fake = _NotesFake();
    await tester.pumpWidget(MaterialApp(home: NotesScreen(clientFactory: (_) => fake, testAccountReady: true)));
    await tester.pumpAndSettle();
    expect(find.text('Order more screws'), findsOneWidget);
    expect(find.textContaining('spoken'), findsOneWidget);

    await tester.enterText(find.byKey(const ValueKey('note-text')), 'Ring the scaffolder');
    await tester.tap(find.byKey(const ValueKey('note-save')));
    await tester.pumpAndSettle();
    expect(find.text('Ring the scaffolder'), findsOneWidget);

    await tester.tap(find.byTooltip('Delete note').first);
    await tester.pumpAndSettle();
    expect(find.text('Delete this note?'), findsOneWidget);
    await tester.tap(find.text('Keep'));
    await tester.pumpAndSettle();
    expect(fake.notesList, hasLength(2)); // Keep deletes nothing

    await tester.tap(find.byTooltip('Delete note').first);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('note-delete-confirm')));
    await tester.pumpAndSettle();
    expect(fake.notesList, hasLength(1));
    expect(tester.takeException(), isNull);
  });
}

class _NotesFake extends RuntimeClient {
  _NotesFake() : super(AppSettings(runtimeUrl: 'http://reader:8780'));

  final notesList = <Map<String, dynamic>>[
    {'id': 'n1', 'text': 'Order more screws', 'source': 'voice', 'created': '2026-11-03T10:00:00Z', 'due': null},
  ];

  @override
  Future<List<Map<String, dynamic>>> notes() async => [...notesList];

  @override
  Future<Map<String, dynamic>> addNote(String text) async {
    final n = {'id': 'n${notesList.length + 1}', 'text': text, 'source': 'typed', 'created': '2026-11-04T10:00:00Z'};
    notesList.insert(0, n);
    return n;
  }

  @override
  Future<void> deleteNote(String id) async => notesList.removeWhere((n) => n['id'] == id);
}
