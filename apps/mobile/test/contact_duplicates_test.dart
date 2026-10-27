import 'package:accnomos_mobile/widgets/duplicates.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// The possible-duplicates card: evidence and the AI's view per group,
/// Merge with a confirm sheet naming the kept contact, Not the same, and
/// Undo after merging. Callbacks stand in for the reader.
void main() {
  Map<String, dynamic> group({
    List<String> ids = const ['a1', 'b2'],
    bool blocked = false,
    Map<String, dynamic>? ai,
  }) =>
      {
        'contact_ids': ids,
        'contacts': [
          {
            'id': 'a1',
            'name': 'Novex Office Supplies Ltd',
            'vrn': 'GB882431902',
            'email': 'sales@novex.example',
          },
          {
            'id': 'b2',
            'name': 'Novex Office Ltd',
            'vrn': 'GB882431902',
            'email': 'sales@novex.example',
          },
        ],
        'evidence': ['same VAT number GB882431902', 'same email sales@novex.example'],
        'blocked': blocked,
        'ai': ai ??
            {
              'same': true,
              'confidence': 0.9,
              'keep_name': 'Novex Office Supplies Ltd',
              'reason': 'Same VAT number and email.',
            },
      };

  Widget card({
    List<Map<String, dynamic>>? groups,
    Future<Map<String, dynamic>> Function({
      required String keepId,
      required List<String> mergeIds,
      String? name,
    })? onMerge,
    Future<void> Function(List<String> ids)? onDismiss,
    Future<void> Function(String mergeId)? onUndo,
    VoidCallback? onChanged,
  }) {
    return MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: DuplicatesCard(
            groups: groups ?? [group()],
            onMerge: onMerge ??
                ({required keepId, required mergeIds, name}) async =>
                    {
                      'contact': {'id': keepId, 'name': 'Novex Kept'},
                      'merge_id': 'm1',
                    },
            onDismiss: onDismiss ?? (_) async {},
            onUndo: onUndo ?? (_) async {},
            onChanged: onChanged ?? () {},
          ),
        ),
      ),
    );
  }

  Future<void> openGroup(WidgetTester tester) async {
    await tester.tap(find.text('Novex Office Supplies Ltd + Novex Office Ltd'));
    await tester.pumpAndSettle();
  }

  test('duplicateAiText states the view and the confidence', () {
    expect(
        duplicateAiText(
            {
              'same': true,
              'confidence': 0.9,
              'reason': 'Same VAT number and email.',
            },
            false),
        'AI view: same business (90%): Same VAT number and email.');
    expect(
        duplicateAiText(
            {'same': false, 'confidence': 0.2, 'reason': 'Different phones.'},
            false),
        'AI view: not the same (20%): Different phones.');
    expect(duplicateAiText(null, false), isNull);
  });

  testWidgets('empty groups hide the card', (tester) async {
    await tester.pumpWidget(card(groups: const []));
    expect(find.textContaining('Possible duplicates'), findsNothing);
  });

  testWidgets('card names the count and the group', (tester) async {
    await tester.pumpWidget(card());
    expect(find.text('Possible duplicates (1)'), findsOneWidget);
    expect(find.text('Novex Office Supplies Ltd + Novex Office Ltd'),
        findsOneWidget);
  });

  testWidgets('sheet shows evidence and the AI view', (tester) async {
    await tester.pumpWidget(card());
    await openGroup(tester);
    expect(find.text('• same VAT number GB882431902'), findsOneWidget);
    expect(find.textContaining('AI view: same business (90%)'),
        findsOneWidget);
    expect(find.text('Merge'), findsOneWidget);
    expect(find.text('Not the same'), findsOneWidget);
  });

  testWidgets('merge confirms naming the kept contact', (tester) async {
    String? kept;
    List<String>? merged;
    String? mergedName;
    await tester.pumpWidget(card(onMerge: (
        {required keepId, required mergeIds, name}) async {
      kept = keepId;
      merged = mergeIds;
      mergedName = name;
      return {
        'contact': {'id': keepId, 'name': 'Novex Office Supplies Ltd'},
        'merge_id': 'm1',
      };
    }));
    await openGroup(tester);
    await tester.tap(find.text('Merge'));
    await tester.pumpAndSettle();
    expect(find.text('Keep which contact?'), findsOneWidget);
    await tester.tap(find.text('Confirm merge'));
    await tester.pumpAndSettle();
    // The AI's keep_name picked the first contact; the other folds into it.
    expect(kept, 'a1');
    expect(merged, ['b2']);
    expect(mergedName, 'Novex Office Supplies Ltd');
    expect(find.text('Merged into Novex Office Supplies Ltd.'),
        findsOneWidget);
    expect(find.text('Undo'), findsOneWidget);
  });

  testWidgets('undo takes the merge back', (tester) async {
    String? undone;
    var changed = 0;
    await tester.pumpWidget(card(
      onUndo: (id) async => undone = id,
      onChanged: () => changed++,
    ));
    await openGroup(tester);
    await tester.tap(find.text('Merge'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm merge'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Undo'));
    await tester.pumpAndSettle();
    expect(undone, 'm1');
    expect(changed, greaterThanOrEqualTo(2));
    expect(find.text('Merged into'), findsNothing);
  });

  testWidgets('not the same dismisses the pair', (tester) async {
    List<String>? dismissed;
    var changed = 0;
    await tester.pumpWidget(card(
      onDismiss: (ids) async => dismissed = ids,
      onChanged: () => changed++,
    ));
    await openGroup(tester);
    await tester.tap(find.text('Not the same'));
    await tester.pumpAndSettle();
    expect(dismissed, ['a1', 'b2']);
    expect(changed, 1);
  });

  testWidgets('blocked groups show the verdict with no Merge', (tester) async {
    await tester.pumpWidget(card(groups: [
      group(
        blocked: true,
        ai: {
          'same': false,
          'confidence': 1.0,
          'keep_name': '',
          'reason':
              'Code rules this out: the VAT numbers differ, so these are two businesses.',
        },
      ),
    ]));
    await openGroup(tester);
    expect(find.textContaining('Code rules this out'), findsOneWidget);
    expect(find.text('Merge'), findsNothing);
    expect(find.text('Not the same'), findsOneWidget);
  });

  testWidgets('no AI view leaves the evidence alone', (tester) async {
    await tester.pumpWidget(card(groups: [
      {
        'contact_ids': ['a1', 'b2'],
        'contacts': [],
        'evidence': ['share name words: novex'],
        'blocked': false,
        'ai': null,
      },
    ]));
    await tester.tap(find.byType(OutlinedButton).first);
    await tester.pumpAndSettle();
    expect(
        find.text(
            'The model could not answer — decide from the evidence above.'),
        findsOneWidget);
    await tester.tap(find.text('Merge'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm merge'));
    await tester.pumpAndSettle();
    expect(find.text('Choose which contact to keep.'), findsOneWidget);
  });

  testWidgets('sheets do not overflow at 360 dp', (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(card());
    await openGroup(tester);
    await tester.pump();
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('Merge'));
    await tester.pumpAndSettle();
    await tester.pump();
    expect(tester.takeException(), isNull);
  });
}
