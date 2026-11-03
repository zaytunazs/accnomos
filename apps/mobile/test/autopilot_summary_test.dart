import 'package:accnomos_mobile/widgets/autopilot_summary.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Review's Autopilot entries are one compact line, never a pinned list that covers the document.
void main() {
  testWidgets('six approvals are one short line that opens the list', (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var opened = 0;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: Column(children: [
          AutopilotSummary(count: 6, onOpen: () => opened++),
          const Expanded(child: Placeholder(key: Key('document'))),
        ]),
      ),
    ));
    expect(find.text('6 approved by Autopilot · Review or undo'), findsOneWidget);
    expect(find.text('Undo'), findsNothing);
    final line = tester.getSize(find.byKey(const Key('autopilot-summary')));
    expect(line.height, lessThan(80));
    // The document keeps almost the whole screen on the first frame.
    expect(tester.getSize(find.byKey(const Key('document'))).height, greaterThan(600));
    await tester.tap(find.byKey(const Key('autopilot-summary')));
    expect(opened, 1);
  });
}
