import 'package:flutter_test/flutter_test.dart';

import 'package:accnomos_mobile/services/runtime_client.dart';

Map<String, dynamic> posted({
  required String id,
  String? decidedBy,
  String? eventId,
  Object? gross,
}) =>
    {
      'id': id,
      'status': 'posted',
      'decided_by': decidedBy,
      'event_id': eventId,
      'decided_at': '2026-10-21T10:00:00',
      'extracted': {
        'supplier_name': 'Screwfix',
        'gross_total': gross ?? 38.47,
      },
    };

void main() {
  group('AutopilotApproval.fromProposals', () {
    test('keeps Autopilot postings with an event id', () {
      final items = AutopilotApproval.fromProposals([
        posted(id: 'p1', decidedBy: 'autopilot', eventId: 'ev-1'),
      ]);
      expect(items, hasLength(1));
      expect(items.single.proposalId, 'p1');
      expect(items.single.supplier, 'Screwfix');
      expect(items.single.total, 38.47);
      expect(items.single.eventId, 'ev-1');
    });

    test('drops human approvals and entries without events', () {
      final items = AutopilotApproval.fromProposals([
        posted(
            id: 'human',
            decidedBy: 'zoe@example.test',
            eventId: 'ev-9'),
        posted(id: 'no-event', decidedBy: 'autopilot'),
        posted(id: 'undecided', eventId: 'ev-3'),
      ]);
      expect(items, isEmpty);
    });

    test('parses string totals and unknown suppliers', () {
      final items = AutopilotApproval.fromProposals([
        {
          'id': 'p2',
          'decided_by': 'autopilot',
          'event_id': 'ev-2',
          'extracted': {'gross_total': '212.40'},
        },
      ]);
      expect(items.single.total, 212.40);
      expect(items.single.supplier, 'Unknown supplier');
    });
  });
}
