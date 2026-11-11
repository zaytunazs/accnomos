import 'package:flutter/material.dart';

import '../models/paypal.dart';
import '../screens/paypal_common.dart';
import '../services/books.dart';
import '../services/demo.dart';
import '../services/runtime_client.dart';
import '../services/share.dart';
import '../theme.dart';

/// The honest line for an approved payment: PayPal cannot hold a payment for
/// a future date, so Accnomos pays it when next open (lib/billpay-text.ts).
String paysLine(String isoDate) =>
    'Accnomos pays this the next time it is open on or after ${ukDate(isoDate)} '
    '— PayPal cannot hold a payment for a future date.';

/// The calendar the runtime writes to: the signed-in account's own.
String get billPayCalendarName => Demo.active ? 'the demo calendar' : 'your calendar';

/// A small status pill, as the web's StatusPill.
class UpcomingStatusPill extends StatelessWidget {
  const UpcomingStatusPill({super.key, required this.item});

  final UpcomingPayment item;

  @override
  Widget build(BuildContext context) {
    final warn = item.needsYou;
    final strong = item.status == 'scheduled' || item.status == 'due_today';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: warn
            ? const Color(0xFFFFF4E5)
            : strong
                ? AccnomosColors.tealTint
                : AccnomosColors.ground,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(item.statusLabel,
          style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: warn
                  ? AccnomosColors.warnText
                  : strong
                      ? AccnomosColors.tealDark
                      : AccnomosColors.muted)),
    );
  }
}

/// Bill pay › Upcoming PayPal payments, as the web's UpcomingTable: every
/// approved-in-advance and planned payment with its status, what leaves
/// PayPal in the next 7 and 30 days, the shortfall warning, cancelling an
/// approval (after a yes), and the calendar: events in the connected
/// calendar (added, updated and removed by Accnomos on the owner's tap) or an
/// .ics file shared to any calendar app.
class UpcomingPaymentsPanel extends StatefulWidget {
  const UpcomingPaymentsPanel({
    super.key,
    required this.client,
    required this.refresh,
    required this.onChanged,
  });

  final RuntimeClient client;

  /// Changed by the bill pay screen after anything it did: load again.
  final int refresh;
  final Future<void> Function() onChanged;

  @override
  State<UpcomingPaymentsPanel> createState() => _UpcomingPaymentsPanelState();
}

class _UpcomingPaymentsPanelState extends State<UpcomingPaymentsPanel> {
  UpcomingPayments? _u;
  String? _error;
  String? _busy;
  String? _said;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void didUpdateWidget(UpcomingPaymentsPanel old) {
    super.didUpdateWidget(old);
    if (old.refresh != widget.refresh) _reload();
  }

  Future<void> _reload() async {
    try {
      final u = await widget.client.billPayUpcoming();
      if (mounted) {
        setState(() {
          _u = u;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = friendly(e));
    }
  }

  Future<void> _act(String key, Future<String?> Function() run) async {
    if (_busy != null) return;
    setState(() => _busy = key);
    try {
      final said = await run();
      if (mounted) setState(() => _said = said);
      await _reload();
    } catch (e) {
      if (mounted) setState(() => _said = friendly(e));
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  Future<void> _cancel(UpcomingPayment i) async {
    final yes = await confirmAction(context,
        title: 'Cancel this approval?',
        body: 'Nothing will be sent to ${i.supplier} for ${gbp(i.amountPence)} '
            'unless you approve it again.',
        yes: 'Cancel approval');
    if (!yes) return;
    await _act('cancel-${i.eventId}', () async {
      await widget.client.billPayCancelSchedule(i.eventId);
      await widget.onChanged();
      return i.inCalendar
          ? 'Cancelled. Its event is still in $billPayCalendarName: remove it below.'
          : 'Cancelled. Nothing will be sent for it.';
    });
  }

  Future<void> _addLive([UpcomingPayment? i]) =>
      _act('cal-${i?.eventId ?? 'all'}', () async {
        final r = await widget.client
            .billPayAddToCalendar(eventIds: i == null ? null : [i.eventId]);
        final name = billPayCalendarName;
        return '${name[0].toUpperCase()}${name.substring(1)}: ${r.addedSummary}.';
      });

  Future<void> _share([UpcomingPayment? i]) =>
      _act('ics-${i?.eventId ?? 'all'}', () async {
        final text = await widget.client.billPayIcs(eventId: i?.eventId);
        final ok = await ShareText.share(text,
            subject: i == null ? 'PayPal payments' : 'PayPal payment to ${i.supplier}',
            mime: 'text/calendar');
        return ok
            ? 'Calendar file shared. Opening it adds the event; Accnomos cannot '
                'change or remove an event added from a file.'
            : 'No app on this phone took the calendar file. Add it to $billPayCalendarName instead.';
      });

  Future<void> _removeStale() => _act('stale', () async {
        final r = await widget.client.billPayRemoveFromCalendar();
        return 'Removed ${r.removed} from $billPayCalendarName'
            '${r.notFound > 0 ? ' (${r.notFound} had already gone)' : ''}.';
      });

  @override
  Widget build(BuildContext context) {
    final u = _u;
    if (u == null) {
      return _error == null
          ? const SizedBox.shrink()
          : PanelCard(children: [
              Text('Could not load upcoming PayPal payments: $_error', style: panelWarn),
            ]);
    }
    final cal = billPayCalendarName;
    final busy = _busy != null;
    return PanelCard(children: [
      const Text('Upcoming PayPal payments', style: panelTitle),
      const SizedBox(height: 4),
      Text('${u.clearingLabel}: ${gbp(u.clearingPence)}',
          style: panelMuted.copyWith(fontSize: 13)),
      if (u.note.isNotEmpty)
        Text(u.note, style: panelMuted.copyWith(fontSize: 13)),
      const SizedBox(height: 8),
      Row(children: [
        Expanded(child: _total('Leaving PayPal, next 7 days', u.next7Pence)),
        const SizedBox(width: 8),
        Expanded(child: _total('Next 30 days', u.next30Pence)),
      ]),
      if (u.warning != null)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(u.warning!, key: const Key('upcoming-warning'), style: panelWarn),
        ),
      const SizedBox(height: 8),
      if (u.items.isEmpty)
        const Text(
            'No PayPal bill payments are planned. Switch on "Pay with PayPal on '
            'due date" for a bill, or approve one in advance.',
            style: panelMuted)
      else
        for (final i in u.items)
          Container(
            key: ValueKey('upcoming-${i.eventId}'),
            width: double.infinity,
            padding: const EdgeInsets.symmetric(vertical: 8),
            decoration: const BoxDecoration(
                border: Border(top: BorderSide(color: AccnomosColors.border))),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Expanded(
                    child: Text(
                      '${ukDate(i.date)} · ${i.supplier}'
                      '${i.reference != null ? ' · ${i.reference}' : ''}',
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                  ),
                  Text(gbp(i.amountPence),
                      style: const TextStyle(fontWeight: FontWeight.w800)),
                ]),
                const SizedBox(height: 4),
                UpcomingStatusPill(item: i),
                if (i.payeeEmail != null)
                  Text('to ${i.payeeEmail}', style: panelMuted.copyWith(fontSize: 12)),
                if (i.approved && i.status == 'scheduled')
                  Text(paysLine(i.date), style: panelMuted.copyWith(fontSize: 12)),
                if (i.reason != null)
                  Text('${i.reason}.',
                      style: i.needsYou
                          ? panelWarn.copyWith(fontSize: 12)
                          : panelMuted.copyWith(fontSize: 12)),
                Wrap(spacing: 4, children: [
                  if (i.cancellable)
                    TextButton(
                      key: Key('cancel-${i.eventId}'),
                      style: TextButton.styleFrom(
                          foregroundColor: AccnomosColors.warnText,
                          minimumSize: const Size(48, 48)),
                      onPressed: busy ? null : () => _cancel(i),
                      child: const Text('Cancel approval'),
                    ),
                  if (!i.settled) ...[
                    TextButton(
                      key: Key('cal-${i.eventId}'),
                      style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
                      onPressed: busy ? null : () => _addLive(i),
                      child: Text(i.inCalendar
                          ? (i.calendarOutdated ? 'Update in $cal' : 'In $cal ✓')
                          : 'Add to $cal'),
                    ),
                    TextButton(
                      key: Key('ics-${i.eventId}'),
                      style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
                      onPressed: busy ? null : () => _share(i),
                      child: const Text('Share .ics'),
                    ),
                  ] else if (i.inCalendar)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      child: Text('In $cal', style: panelMuted.copyWith(fontSize: 12)),
                    ),
                ]),
              ],
            ),
          ),
      if (u.calendarStale.isNotEmpty) ...[
        const SizedBox(height: 6),
        Text(
          '${u.calendarStale.length} event${u.calendarStale.length == 1 ? ' is' : 's are'} '
          'in $cal for a payment that was cancelled, paid or is no longer planned.',
        ),
        OutlinedButton(
          key: const Key('upcoming-remove-stale'),
          style: OutlinedButton.styleFrom(minimumSize: const Size(48, 48)),
          onPressed: busy ? null : _removeStale,
          child: Text('Remove from $cal'),
        ),
      ],
      if (u.open.isNotEmpty)
        Wrap(spacing: 8, runSpacing: 8, children: [
          OutlinedButton(
            key: const Key('upcoming-add-all'),
            style: OutlinedButton.styleFrom(minimumSize: const Size(48, 48)),
            onPressed: busy ? null : () => _addLive(),
            child: Text('Add all to $cal'),
          ),
          OutlinedButton(
            style: OutlinedButton.styleFrom(minimumSize: const Size(48, 48)),
            onPressed: busy ? null : () => _share(),
            child: const Text('Share all (.ics)'),
          ),
        ]),
      const SizedBox(height: 6),
      Text(
        'Calendar events are all-day on the due date. Added to $cal by Accnomos, '
        'they are updated when you add them again and can be removed here; a '
        'shared file is yours to change.',
        style: panelMuted.copyWith(fontSize: 12),
      ),
      if (_said != null)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(_said!,
              key: const Key('upcoming-said'),
              style: const TextStyle(fontWeight: FontWeight.w700)),
        ),
    ]);
  }

  Widget _total(String label, int pence) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
            color: AccnomosColors.ground, borderRadius: BorderRadius.circular(10)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: panelMuted.copyWith(fontSize: 12)),
          Text(gbp(pence),
              style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
        ]),
      );
}

/// Home › Upcoming PayPal payments, as the web's UpcomingPaymentsCard: the
/// next five, what leaves PayPal in the next 30 and 7 days and the shortfall
/// warning. Opening Home is opening the app, so it first runs
/// `POST /billpay/run` (follow payouts, pay approvals whose date has come,
/// Autopilot within the owner's rules), as the web does. Hidden when nothing
/// is planned.
class UpcomingPaymentsHomeCard extends StatefulWidget {
  const UpcomingPaymentsHomeCard({
    super.key,
    required this.client,
    required this.onOpen,
    this.refresh = 0,
  });

  final RuntimeClient client;
  final VoidCallback onOpen;
  final int refresh;

  @override
  State<UpcomingPaymentsHomeCard> createState() => _UpcomingPaymentsHomeCardState();
}

class _UpcomingPaymentsHomeCardState extends State<UpcomingPaymentsHomeCard> {
  static const _shown = 5;
  UpcomingPayments? _u;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(UpcomingPaymentsHomeCard old) {
    super.didUpdateWidget(old);
    if (old.refresh != widget.refresh || old.client != widget.client) _load();
  }

  Future<void> _load() async {
    try {
      await widget.client.billPayRun();
    } catch (_) {
      // A demo or no PayPal: the schedule still shows.
    }
    try {
      final u = await widget.client.billPayUpcoming();
      if (mounted) setState(() => _u = u);
    } catch (_) {
      // An older runtime or personal books: the card stays hidden.
    }
  }

  @override
  Widget build(BuildContext context) {
    final u = _u;
    if (u == null || u.items.isEmpty) return const SizedBox.shrink();
    final next = [for (final i in u.items) if (i.status != 'paid') i].take(_shown).toList();
    final warn = u.warning != null || next.any((i) => i.needsYou);
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: PanelCard(warn: warn, children: [
        const Text('Upcoming PayPal payments',
            key: Key('home-upcoming-paypal'), style: panelTitle),
        const SizedBox(height: 4),
        Text(gbp(u.next30Pence),
            style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
        Text('leaving PayPal in the next 30 days · ${gbp(u.next7Pence)} in the next 7',
            style: panelMuted.copyWith(fontSize: 13)),
        if (u.warning != null)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(u.warning!, style: panelWarn),
          ),
        const SizedBox(height: 8),
        for (final i in next)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${i.supplier} · ${ukDate(i.date)}',
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  const SizedBox(height: 2),
                  UpcomingStatusPill(item: i),
                ]),
              ),
              const SizedBox(width: 8),
              Text(gbp(i.amountPence), style: const TextStyle(fontWeight: FontWeight.w800)),
            ]),
          ),
        if (u.note.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(u.note, style: panelMuted.copyWith(fontSize: 12)),
          ),
        Text('Dates and totals by code; the AI pays nothing.',
            style: panelMuted.copyWith(fontSize: 12)),
        const SizedBox(height: 8),
        FilledButton(
          key: const Key('home-open-billpay'),
          style: FilledButton.styleFrom(
              backgroundColor: AccnomosColors.teal, minimumSize: const Size(48, 48)),
          onPressed: widget.onOpen,
          child: const Text('Open bill pay'),
        ),
      ]),
    );
  }
}
