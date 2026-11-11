import 'package:flutter/material.dart';

import '../models/paypal.dart';
import '../services/books.dart';
import '../services/runtime_client.dart';
import '../theme.dart';
import '../widgets/web_only.dart';
import 'paypal_common.dart';

/// More › Bill pay, as the web's BillPay panel: suppliers' bills paid from
/// PayPal on their due date. Opening it follows payouts already on their way
/// and lets bill-pay Autopilot pay only what the owner's own rules allow
/// (`POST /billpay/run`); everything else waits here. The owner approves and
/// pays each bill on the phone, chooses which bills go through PayPal,
/// clears a changed-details warning after ringing the supplier, and can
/// stop all automatic payments. Typing suppliers' PayPal emails and setting
/// Autopilot's limits stay on the web (see [_webOnly]).
class BillPayScreen extends StatefulWidget {
  const BillPayScreen({super.key, this.clientFactory, this.runOnOpen = true});

  final PayPalClientFactory? clientFactory;

  /// Run `POST /billpay/run` when the screen opens, as the web does.
  final bool runOnOpen;

  @override
  State<BillPayScreen> createState() => _BillPayScreenState();
}

class _BillPayScreenState extends State<BillPayScreen> {
  RuntimeClient? _client;
  bool _ready = false;
  bool _loading = false;
  String? _busy;
  String? _error;
  BillPayOverview? _o;
  List<String> _problems = const [];

  @override
  void initState() {
    super.initState();
    _start();
  }

  Future<void> _start() async {
    RuntimeClient? client;
    try {
      client = await (widget.clientFactory ?? defaultPayPalClient)();
    } catch (_) {
      client = null;
    }
    if (!mounted) return;
    setState(() {
      _client = client;
      _ready = true;
    });
    if (client == null) return;
    if (widget.runOnOpen) {
      try {
        final run = await client.billPayRun();
        if (mounted) setState(() => _problems = run.problems);
      } catch (_) {
        // Not connected, or a demo where nothing real may move: the
        // overview still loads and says why.
      }
    }
    await _reload();
  }

  Future<void> _reload() async {
    final client = _client;
    if (client == null || _loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final o = await client.billPay();
      if (mounted) setState(() => _o = o);
    } catch (e) {
      if (mounted) setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _act(String key, Future<void> Function(RuntimeClient c) run) async {
    final client = _client;
    if (client == null || _busy != null) return;
    setState(() {
      _busy = key;
      _error = null;
    });
    try {
      await run(client);
      if (mounted) setState(() => _busy = null);
      await _reload();
    } catch (e) {
      if (mounted) setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        title: const Text('Bill pay'),
        actions: [
          if (_client != null)
            IconButton(
              icon: const Icon(Icons.refresh_outlined),
              tooltip: 'Reload bills',
              constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : _reload,
            ),
        ],
      ),
      body: !_ready || (_loading && _o == null)
          ? const Center(child: CircularProgressIndicator())
          : _client == null
              ? const PayPalSignedOut(what: 'pay bills with PayPal')
              : RefreshIndicator(onRefresh: _reload, child: _body()),
    );
  }

  Widget _body() {
    final o = _o;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
      children: [
        Text(
          'Bills you approved in Review can be paid from your PayPal account on '
          'their due date. You approve each payment, or let Autopilot pay '
          'suppliers you set limits for. A supplier\'s PayPal email is only '
          'ever one you typed, never one read from a bill.'
          '${o?.testMode ?? false ? ' PayPal sandbox: no real money moves.' : ''}',
          style: panelMuted,
        ),
        const SizedBox(height: 12),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(_error!, key: const Key('billpay-error'), style: panelWarn),
          ),
        if (o != null) ...[
          if (!o.available && o.reason != null)
            PanelCard(children: [Text(o.reason!, style: panelMuted)]),
          if (o.available && !o.connected)
            const PanelCard(children: [
              Text('PayPal is not connected to these books.', style: panelMuted),
              WebOnlyCard(
                message:
                    'Connecting PayPal signs you in on PayPal\'s own page, so it '
                    'is done in Settings › Online payments on the web.',
                page: '/settings#settings-payments',
              ),
            ]),
          _notices(o),
          _flags(o),
          _dueToday(o),
          _bills(o),
          _payees(o),
          _autopilot(o),
          _payouts(o),
        ],
      ],
    );
  }

  Widget _notices(BillPayOverview o) {
    if (o.notices.isEmpty && _problems.isEmpty) return const SizedBox.shrink();
    return PanelCard(children: [
      for (final n in o.notices)
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Text(n.text, style: n.loud ? panelWarn : null),
        ),
      for (final p in _problems)
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Text(p, style: panelWarn),
        ),
      if (o.notices.isNotEmpty)
        TextButton(
          style: TextButton.styleFrom(
              padding: EdgeInsets.zero, minimumSize: const Size(48, 48)),
          onPressed: _busy != null
              ? null
              : () => _act('seen', (c) => c.billPayNoticesSeen(
                  [for (final n in o.notices) n.id])),
          child: const Text('Mark as read'),
        ),
    ]);
  }

  Widget _flags(BillPayOverview o) {
    if (o.flags.isEmpty) return const SizedBox.shrink();
    return PanelCard(warn: true, children: [
      const Text('Payment details changed on a bill', style: panelTitle),
      const SizedBox(height: 4),
      const Text(
        'Changed bank or PayPal details on a bill are a common fraud. Accnomos '
        'keeps paying the details you saved and has stopped Autopilot for these '
        'suppliers. Ring the supplier on a number you already had (not one on '
        'the bill) before you change anything.',
        style: TextStyle(height: 1.4),
      ),
      for (final f in o.flags) ...[
        const SizedBox(height: 8),
        Text('${f.supplier}: ${f.reason}.',
            style: const TextStyle(fontWeight: FontWeight.w700)),
        OutlinedButton(
          style: OutlinedButton.styleFrom(minimumSize: const Size(48, 48)),
          onPressed: _busy != null
              ? null
              : () async {
                  final yes = await confirmAction(context,
                      title: 'Checked with ${f.supplier}?',
                      body:
                          'Only say yes if you rang ${f.supplier} on a number you already had and they confirmed their payment details.',
                      yes: 'I checked');
                  if (yes) {
                    await _act('flag-${f.id}', (c) => c.billPayClearFlag(f.id));
                  }
                },
          child: const Text('I checked with the supplier'),
        ),
      ],
    ]);
  }

  Widget _dueToday(BillPayOverview o) {
    return PanelCard(children: [
      const Text('Due today', style: panelTitle),
      Text('1240 PayPal clearing by your books: ${gbp(o.clearingPence)}',
          style: panelMuted.copyWith(fontSize: 13)),
      const SizedBox(height: 8),
      if (o.due.isEmpty)
        const Text('No bill is due for PayPal today.',
            key: Key('billpay-none-due'), style: panelMuted)
      else
        for (final b in o.due)
          DueBillCard(
            key: ValueKey('due-${b.eventId}'),
            bill: b,
            busy: _busy != null,
            paying: _busy == 'pay-${b.eventId}',
            onPay: (ack) => _act('pay-${b.eventId}',
                (c) => c.billPayPay(b.eventId, b.owedPence,
                    acknowledgeChangedDetails: ack)),
          ),
    ]);
  }

  Widget _bills(BillPayOverview o) {
    final bills = [...o.due, ...o.upcoming]
      ..sort((x, y) => x.dueDate.compareTo(y.dueDate));
    if (bills.isEmpty) return const SizedBox.shrink();
    return PanelCard(children: [
      const Text('Due later', style: panelTitle),
      const SizedBox(height: 4),
      for (final b in bills)
        SwitchListTile(
          key: ValueKey('plan-${b.eventId}'),
          contentPadding: EdgeInsets.zero,
          value: b.payWithPayPal,
          onChanged: _busy != null
              ? null
              : (on) => _act('plan-${b.eventId}',
                  (c) => c.billPayPlan(b.eventId, on ? 'paypal' : 'not_paypal')),
          title: Text(
              '${b.supplier}${b.reference != null ? ' · ${b.reference}' : ''}',
              style: const TextStyle(fontWeight: FontWeight.w700)),
          subtitle: Text(
            '${gbp(b.owedPence)} · ${dueLine(b)}'
            '${b.payeeEmail == null ? ' · no PayPal email saved' : ''}\n'
            'Pay with PayPal on due date',
            style: panelMuted.copyWith(fontSize: 13),
          ),
        ),
    ]);
  }

  Widget _payees(BillPayOverview o) {
    return PanelCard(children: [
      const Text("Suppliers' PayPal emails", style: panelTitle),
      const SizedBox(height: 4),
      if (o.payees.isEmpty)
        const Text('None saved yet.', style: panelMuted)
      else
        for (final p in o.payees)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Text(
              '${p.name} · ${p.paypalEmail}'
              '${p.bank != null ? ' · bank ${p.bank}' : ''}'
              '${p.confirmedAt != null ? ' · confirmed ${ukDate(p.confirmedAt!)}' : ''}',
            ),
          ),
      const WebOnlyCard(
        message:
            'Adding, changing or removing a supplier\'s PayPal email is done on '
            'the web: you type it from details checked with the supplier, and a '
            'change restarts Autopilot\'s waiting days, so it is kept to a '
            'deliberate step at a desk.',
        page: '/purchases',
      ),
    ]);
  }

  Widget _autopilot(BillPayOverview o) {
    final a = o.autopilot;
    return PanelCard(children: [
      Row(children: [
        const Expanded(child: Text('Autopilot for bills', style: panelTitle)),
        Text(a.label,
            key: const Key('billpay-autopilot-state'),
            style: const TextStyle(fontWeight: FontWeight.w800)),
      ]),
      const SizedBox(height: 4),
      if (a.enabled)
        Text(
            'Pays ${a.suppliers} supplier${a.suppliers == 1 ? '' : 's'} within the limits you set.',
            style: panelMuted),
      if (o.autopilotNote.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(o.autopilotNote, style: panelMuted.copyWith(fontSize: 13)),
        ),
      if (a.enabled)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: OutlinedButton(
            key: const Key('billpay-stop'),
            style: OutlinedButton.styleFrom(
                foregroundColor: AccnomosColors.warnText,
                side: const BorderSide(color: AccnomosColors.warnText, width: 2),
                minimumSize: const Size.fromHeight(48)),
            onPressed: _busy != null
                ? null
                : () async {
                    final yes = await confirmAction(context,
                        title: 'Stop all automatic payments?',
                        body:
                            'Autopilot pays nothing more until you switch it on again on the web. Bills still wait here for you.',
                        yes: 'Stop now');
                    if (yes) await _act('stop', (c) => c.billPayStopAutopilot());
                  },
            child: const Text('Stop all automatic payments now'),
          ),
        ),
      const WebOnlyCard(
        message:
            'Switching Autopilot on and setting each supplier\'s limits (most per '
            'bill, most per month, days the email must be unchanged) is done on '
            'the web, where the whole table of suppliers can be checked at once. '
            'Stopping it works here.',
        page: '/purchases',
      ),
    ]);
  }

  Widget _payouts(BillPayOverview o) {
    if (o.payouts.isEmpty) return const SizedBox.shrink();
    return PanelCard(children: [
      const Text('PayPal payments to suppliers', style: panelTitle),
      for (final p in o.payouts.take(20))
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${p.supplier}${p.reference != null ? ' · ${p.reference}' : ''} · ${gbp(p.amountPence)}',
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              Text(
                'to ${p.receiver} · ${p.via == 'autopilot' ? 'by Autopilot' : 'approved by you'}'
                '${p.createdAt != null ? ' · ${ukDate(p.createdAt!)}' : ''} · ${p.statusLabel}'
                '${p.feePence != null && p.feePence! > 0 ? ' (PayPal fee ${gbp(p.feePence!)})' : ''}'
                '${p.detail != null ? '. ${p.detail}.' : ''}',
                style: panelMuted.copyWith(fontSize: 13),
              ),
              if (p.problem != null) Text('${p.problem}.', style: panelWarn),
            ],
          ),
        ),
    ]);
  }
}

/// "due today", "due 12 Nov 2026, 2 days overdue" or "due 20 Nov 2026".
String dueLine(BillPayBill b) {
  if (b.daysOverdue > 0) {
    return 'due ${ukDate(b.dueDate)}, ${b.daysOverdue} day${b.daysOverdue == 1 ? '' : 's'} overdue';
  }
  if (b.daysOverdue == 0) return 'due today';
  return 'due ${ukDate(b.dueDate)}';
}

/// One bill due now: Approve payment opens the confirmation (amount, who it
/// pays, what posts); a bill with changed payment details also needs the
/// owner's tick that they checked with the supplier.
class DueBillCard extends StatefulWidget {
  const DueBillCard({
    super.key,
    required this.bill,
    required this.busy,
    required this.paying,
    required this.onPay,
  });

  final BillPayBill bill;
  final bool busy;
  final bool paying;
  final void Function(bool acknowledgeChangedDetails) onPay;

  @override
  State<DueBillCard> createState() => _DueBillCardState();
}

class _DueBillCardState extends State<DueBillCard> {
  bool _asking = false;
  bool _ack = false;

  @override
  Widget build(BuildContext context) {
    final b = widget.bill;
    final p = b.payout;
    final changed = b.changedDetails.isNotEmpty;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
          border: Border.all(color: AccnomosColors.border),
          borderRadius: BorderRadius.circular(10)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              child: Text(
                  '${b.supplier}${b.reference != null ? ' · ${b.reference}' : ''}',
                  style: const TextStyle(fontWeight: FontWeight.w800)),
            ),
            Text(gbp(b.owedPence),
                style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
          ]),
          Text(
              '${dueLine(b)}${b.payeeEmail != null ? ' · pays ${b.payeeEmail}' : ''}',
              style: panelMuted.copyWith(fontSize: 13)),
          if (changed)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text('${b.changedDetails.join('. ')}.', style: panelWarn),
            ),
          for (final w in b.warnings.where((w) => !b.changedDetails.contains(w)))
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('$w.', style: panelWarn),
            ),
          for (final w in b.blocks)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('$w.', style: panelMuted),
            ),
          if (p != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                  '${p.statusLabel}${p.detail != null ? ': ${p.detail}.' : '.'}',
                  style: const TextStyle(fontWeight: FontWeight.w700)),
            ),
          if (b.canPay && !_asking)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: FilledButton(
                key: Key('approve-pay-${b.eventId}'),
                style: FilledButton.styleFrom(
                    backgroundColor: AccnomosColors.teal,
                    minimumSize: const Size(48, 48)),
                onPressed: widget.busy ? null : () => setState(() => _asking = true),
                child: Text(p?.status == 'failed' ? 'Try again' : 'Approve payment'),
              ),
            ),
          if (b.canPay && _asking)
            Container(
              margin: const EdgeInsets.only(top: 8),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                  border: Border.all(color: AccnomosColors.border),
                  borderRadius: BorderRadius.circular(10)),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Pay ${gbp(b.owedPence)} to ${b.payeeEmail ?? b.supplier} from '
                    'your PayPal account now? When PayPal says it is paid, '
                    'Accnomos posts it: 2100 Creditors debit, 1240 PayPal clearing credit.',
                  ),
                  if (changed)
                    CheckboxListTile(
                      key: Key('ack-${b.eventId}'),
                      contentPadding: EdgeInsets.zero,
                      controlAffinity: ListTileControlAffinity.leading,
                      value: _ack,
                      onChanged: (v) => setState(() => _ack = v ?? false),
                      title: Text(
                        'I checked with the supplier, by phone on a number I '
                        'already had, that ${b.payeeEmail ?? 'the PayPal email'} is right.',
                        style: panelWarn,
                      ),
                    ),
                  const SizedBox(height: 6),
                  Wrap(spacing: 8, runSpacing: 8, children: [
                    FilledButton(
                      key: Key('pay-${b.eventId}'),
                      style: FilledButton.styleFrom(
                          backgroundColor: AccnomosColors.teal,
                          minimumSize: const Size(48, 48)),
                      onPressed: widget.busy || (changed && !_ack)
                          ? null
                          : () => widget.onPay(_ack),
                      child: Text(widget.paying
                          ? 'Paying…'
                          : 'Pay ${gbp(b.owedPence)}'),
                    ),
                    OutlinedButton(
                      style: OutlinedButton.styleFrom(
                          minimumSize: const Size(48, 48)),
                      onPressed: () => setState(() => _asking = false),
                      child: const Text('Cancel'),
                    ),
                  ]),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
