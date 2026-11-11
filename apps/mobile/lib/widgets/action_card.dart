import 'package:flutter/material.dart';

import '../models/ask_answer.dart' show ProposedAction;
import '../services/runtime_client.dart';
import '../theme.dart';

/// Labels for the signed cards the month-end close proposes
/// (services/runtime/app/month_end.py), as the web's cards name them.
const actionKindLabels = <String, String>{
  'chase_invoice': 'Chase invoice',
  'match_bank_line': 'Match bank line',
  'close_month': 'Close the month',
  'create_invoice': 'Invoice',
  'log_timesheet': 'Log hours',
  'record_payment': 'Record payment',
  'save_note': 'Note',
  'delete_note': 'Delete note',
  'add_todo': 'To-do',
  'calendar_add_event': 'Add to calendar',
  'calendar_remove_event': 'Remove from calendar',
  'calendar_move_event': 'Move in calendar',
  'remind_unpaid': 'Payment reminders',
  'payment_link_message': 'Payment message',
};

/// One signed card that does nothing until approved: summary, warnings,
/// the confirm sentence and Approve / Reject. Approving posts the card back
/// unchanged (`POST /actions/approve`), exactly as the web's card does; the
/// runtime refuses it if anything in it changed or it has expired.
class ProposedActionCard extends StatefulWidget {
  const ProposedActionCard({
    super.key,
    required this.action,
    required this.clientFor,
    this.onDone,
  });

  final ProposedAction action;
  final Future<RuntimeClient> Function() clientFor;

  /// Called after an approve or reject went through (true = approved).
  final void Function(bool approved)? onDone;

  @override
  State<ProposedActionCard> createState() => _ProposedActionCardState();
}

class _ProposedActionCardState extends State<ProposedActionCard> {
  bool _busy = false;
  String? _result;
  String? _error;

  static String _plain(String md) => md
      .replaceAll(RegExp(r'^> ?', multiLine: true), '')
      .replaceAllMapped(RegExp(r'\\(.)'), (m) => m.group(1)!)
      .replaceAll('**', '');

  Future<void> _decide(bool approve) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final client = await widget.clientFor();
      final text = approve
          ? await client.approveAction(widget.action)
          : await client.rejectAction(widget.action);
      if (!mounted) return;
      setState(() => _result = approve ? text : 'Rejected. Nothing was done.');
      widget.onDone?.call(approve);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final a = widget.action;
    final expires = a.expiresAt;
    final expired = expires != null && DateTime.now().isAfter(expires);
    final title = actionKindLabels[a.kind] ?? 'Proposed action';
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AccnomosColors.teal, width: 1.5),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('$title · needs your OK',
              style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  color: AccnomosColors.tealDark)),
          const SizedBox(height: 6),
          Text(_plain(a.summaryMd), style: const TextStyle(height: 1.4)),
          for (final w in a.warnings)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(w,
                  style: const TextStyle(
                      color: Color(0xFF8A470D), fontSize: 13, height: 1.4)),
            ),
          const SizedBox(height: 10),
          if (_result != null)
            Text('✓ ${_plain(_result!)}',
                style: const TextStyle(
                    color: AccnomosColors.tealDark,
                    fontWeight: FontWeight.w700,
                    height: 1.4))
          else ...[
            Text(
              expired
                  ? 'This card has expired; run the close again.'
                  : (a.confirmText.isEmpty ? 'Approve this?' : '${a.confirmText}?'),
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(_error!,
                    style: const TextStyle(color: Color(0xFFA12626), height: 1.4)),
              ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                FilledButton(
                  onPressed: _busy || expired ? null : () => _decide(true),
                  child: Text(_busy ? 'Working…' : 'Approve'),
                ),
                OutlinedButton(
                  onPressed: _busy ? null : () => _decide(false),
                  child: const Text('Reject'),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
