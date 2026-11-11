import 'package:flutter/material.dart';

import '../models/paypal.dart';
import '../services/books.dart';
import '../services/runtime_client.dart';
import '../theme.dart';
import '../widgets/web_only.dart';
import 'paypal_common.dart';

/// Invoices › Sync PayPal, as the web's PayPalSync + PayPalTieOut: one tap
/// reads the PayPal history and each transaction waits here for the owner's
/// yes. Code works out every figure; nothing posts on its own. A sale with
/// no invoice in VAT-registered books cannot be approved until the owner
/// chooses its VAT. Above the list: whether PayPal is connected, and PayPal's
/// own balance against 1240 PayPal clearing with the gap explained.
class PayPalSyncScreen extends StatefulWidget {
  const PayPalSyncScreen({super.key, this.clientFactory});

  /// Null: the signed-in (or demo) client.
  final PayPalClientFactory? clientFactory;

  @override
  State<PayPalSyncScreen> createState() => _PayPalSyncScreenState();
}

class _PayPalSyncScreenState extends State<PayPalSyncScreen> {
  RuntimeClient? _client;
  bool _ready = false;
  bool _loading = false;
  bool _syncing = false;
  bool _showRest = false;
  String? _error;
  String? _note;
  PayPalSyncView? _view;
  PayProviderStatus? _paypal;
  bool _providersKnown = false;
  PayPalTieOut? _tie;
  PayPalFees? _fees;

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
    if (client != null) await _reload();
  }

  Future<void> _reload() async {
    final client = _client;
    if (client == null || _loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final view = await client.paypalSyncView();
      if (!mounted) return;
      setState(() => _view = view);
    } catch (e) {
      if (mounted) setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
    // The extras: each one quietly absent when the runtime cannot say.
    try {
      final providers = await client.payProviders();
      if (mounted) {
        setState(() {
          _paypal = PayProviderStatus.paypal(providers);
          _providersKnown = true;
        });
      }
    } catch (_) {}
    await _reloadTie();
    try {
      final now = DateTime.now();
      final fees = await client.paypalFees(
          isoDate(DateTime(now.year, now.month, 1)), isoDate(now));
      if (mounted) setState(() => _fees = fees);
    } catch (_) {}
  }

  Future<void> _reloadTie() async {
    try {
      final tie = await _client!.paypalTieOut();
      if (mounted) setState(() => _tie = tie);
    } catch (_) {
      if (mounted) setState(() => _tie = null);
    }
  }

  Future<void> _sync() async {
    final client = _client;
    if (client == null || _syncing) return;
    setState(() {
      _syncing = true;
      _error = null;
      _note = null;
    });
    try {
      final out = await client.paypalSync(ai: true);
      if (!mounted) return;
      setState(() {
        _view = (_view ?? const PayPalSyncView(available: true)).copyWith(
            items: out.items,
            lastSyncedAt: DateTime.now().toUtc().toIso8601String());
        _note = out.summary;
      });
      await _reloadTie();
    } catch (e) {
      if (mounted) setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _syncing = false);
    }
  }

  void _changed(PayPalSyncItem item, String message) {
    final view = _view;
    if (view == null) return;
    setState(() {
      _view = view.copyWith(items: [
        for (final i in view.items)
          i.transactionId == item.transactionId ? item : i,
      ]);
      _note = message;
    });
    if (item.status == 'approved') _reloadTie();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        title: const Text('Sync PayPal'),
        actions: [
          if (_client != null)
            IconButton(
              icon: const Icon(Icons.refresh_outlined),
              tooltip: 'Reload PayPal',
              constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : _reload,
            ),
        ],
      ),
      body: !_ready || (_loading && _view == null)
          ? const Center(child: CircularProgressIndicator())
          : _client == null
              ? const PayPalSignedOut(what: 'sync PayPal into your books')
              : RefreshIndicator(onRefresh: _reload, child: _body()),
    );
  }

  Widget _body() {
    final view = _view;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
      children: [
        if (_providersKnown) PayPalConnectionCard(status: _paypal),
        if (_tie != null && _tie!.shown && !(view?.sample ?? false))
          PayPalTieOutCard(tie: _tie!),
        if (view != null) _header(view),
        if (_note != null)
          Container(
            key: const Key('paypal-note'),
            margin: const EdgeInsets.only(bottom: 12),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
                color: AccnomosColors.tealTint,
                borderRadius: BorderRadius.circular(12)),
            child: Text(_note!,
                style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    color: AccnomosColors.tealDark)),
          ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(_error!, style: panelWarn),
          ),
        if (view != null)
          for (final item in view.waiting)
            PayPalSyncCard(
              key: ValueKey('sync-${item.transactionId}'),
              item: item,
              client: _client!,
              onChanged: _changed,
            ),
        if (view != null && view.rest.isNotEmpty) _rest(view.rest),
        if (_fees != null && _fees!.transactions > 0)
          PanelCard(children: [
            const Text('PayPal fees this month', style: panelTitle),
            const SizedBox(height: 4),
            Text(
              '${gbp(_fees!.feesPence)} on ${_fees!.transactions} payment'
              '${_fees!.transactions == 1 ? '' : 's'} · '
              '${gbp(_fees!.feesInBooksPence)} in your books (7900 Bank charges)',
              style: panelMuted,
            ),
          ]),
      ],
    );
  }

  Widget _header(PayPalSyncView view) {
    return PanelCard(children: [
      const Text('PayPal', style: panelTitle),
      const SizedBox(height: 4),
      Text(
        '${view.lastSyncedAt != null ? 'Last synced ${ukDate(view.lastSyncedAt!)}. ' : ''}'
        'Every transaction waits for your approval; nothing goes in your books on its own.',
        style: panelMuted,
      ),
      if (view.sample) ...[
        const SizedBox(height: 6),
        const Text(
            'Sample PayPal history for this demo, not a real PayPal account.',
            style: panelWarn),
      ],
      const SizedBox(height: 10),
      if (view.available)
        FilledButton.icon(
          key: const Key('paypal-sync-button'),
          style: FilledButton.styleFrom(
              backgroundColor: AccnomosColors.teal,
              minimumSize: const Size.fromHeight(48)),
          icon: const Icon(Icons.sync_outlined),
          onPressed: _syncing ? null : _sync,
          label: Text(_syncing ? 'Syncing PayPal…' : 'Sync PayPal'),
        )
      else
        Text(view.reason ?? 'PayPal is not connected to these books.',
            style: panelMuted),
      if (view.available && view.waiting.isEmpty && view.items.isNotEmpty)
        const Padding(
          padding: EdgeInsets.only(top: 8),
          child: Text('Nothing is waiting for you.', style: panelMuted),
        ),
    ]);
  }

  Widget _rest(List<PayPalSyncItem> rest) {
    return PanelCard(children: [
      TextButton(
        style: TextButton.styleFrom(
            padding: EdgeInsets.zero, minimumSize: const Size(48, 48)),
        onPressed: () => setState(() => _showRest = !_showRest),
        child: Text(
          '${_showRest ? 'Hide' : 'Show'} ${rest.length} other PayPal '
          'transaction${rest.length == 1 ? '' : 's'}',
          style: const TextStyle(fontWeight: FontWeight.w800),
        ),
      ),
      if (_showRest)
        for (final i in rest)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('${ukDate(i.date)} · ${i.name}',
                          style: const TextStyle(fontWeight: FontWeight.w700)),
                      Text('${i.kindLabel} · ${i.statusLabel}',
                          style: panelMuted),
                      if (i.notes.isNotEmpty)
                        Text(i.notes.first,
                            style: panelMuted.copyWith(fontSize: 13)),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                Text(i.currency == 'GBP' ? gbp(i.grossPence) : i.currency,
                    style: const TextStyle(fontWeight: FontWeight.w800)),
              ],
            ),
          ),
    ]);
  }
}

/// One transaction waiting for the owner: what it is, the fee, the notes,
/// the journal approving posts, and Reject / Approve.
class PayPalSyncCard extends StatefulWidget {
  const PayPalSyncCard({
    super.key,
    required this.item,
    required this.client,
    required this.onChanged,
  });

  final PayPalSyncItem item;
  final RuntimeClient client;
  final void Function(PayPalSyncItem item, String message) onChanged;

  @override
  State<PayPalSyncCard> createState() => _PayPalSyncCardState();
}

class _PayPalSyncCardState extends State<PayPalSyncCard> {
  late String? _account = widget.item.account;
  late String? _vat = widget.item.vatCode ??
      (widget.item.needsVatChoice ? null : 'N');
  bool _busy = false;
  String? _error;

  PayPalSyncItem get item => widget.item;
  int get _gross => item.grossPence.abs();

  /// Approve stays off until a sale with no invoice has its VAT chosen.
  bool get _canApprove => !_busy && (!item.needsVatChoice || _vat != null);

  Future<void> _approve() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final changed = item.editable &&
          (_account != item.account || _vat != item.vatCode);
      final out = item.needsVatChoice
          ? await widget.client.paypalSyncApprove(item.transactionId, vatCode: _vat)
          : changed
              ? await widget.client.paypalSyncApprove(item.transactionId,
                  account: _account, vatCode: _vat)
              : await widget.client.paypalSyncApprove(item.transactionId);
      widget.onChanged(out,
          '${item.kindLabel} of ${gbp(_gross)} (${item.name}) is in your books.');
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = friendly(e);
          _busy = false;
        });
      }
    }
  }

  Future<void> _reject() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final out = await widget.client.paypalSyncReject(item.transactionId);
      widget.onChanged(out, 'Rejected: ${item.name}, ${gbp(_gross)}.');
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = friendly(e);
          _busy = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final i = item;
    return PanelCard(children: [
      Text(
        '${i.kindLabel} · ${i.name} · ${i.grossPence < 0 ? 'paid' : 'received'} '
        '${gbp(_gross)} on ${ukDate(i.date)}'
        '${i.invoice != null ? ' · ${i.invoice}' : ''}',
        style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15),
      ),
      const SizedBox(height: 4),
      Text(
        [
          if (i.items.isNotEmpty) i.items.join(', '),
          i.feePence > 0
              ? 'PayPal fee ${gbp(i.feePence)} · you receive ${gbp(i.netPence)}'
              : 'No PayPal fee',
          if (i.codedBy != null) 'coded by ${i.codedBy}',
        ].join(' · '),
        style: panelMuted.copyWith(fontSize: 13),
      ),
      for (final n in i.notes)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(n,
              style: n.startsWith('No receipt') ||
                      n.contains('twice') ||
                      n.contains('not both')
                  ? panelWarn.copyWith(fontSize: 13)
                  : panelMuted.copyWith(fontSize: 13)),
        ),
      JournalPreview(lines: i.journal),
      if (i.needsVatChoice) ...[
        const SizedBox(height: 10),
        DropdownButtonFormField<String>(
          key: Key('vat-choice-${i.transactionId}'),
          initialValue: _vat,
          isExpanded: true,
          decoration: const InputDecoration(
            labelText: 'VAT on this sale (choose before approving)',
            border: OutlineInputBorder(),
          ),
          hint: const Text('Choose…'),
          items: [
            for (final c in paypalSaleVatCodes)
              DropdownMenuItem(
                  value: c, child: Text(paypalVatLabels[c] ?? c)),
          ],
          onChanged: _busy ? null : (v) => setState(() => _vat = v),
        ),
      ],
      if (i.editable) ...[
        const SizedBox(height: 10),
        DropdownButtonFormField<String>(
          initialValue:
              paypalCostAccounts.contains(_account) ? _account : null,
          isExpanded: true,
          decoration: const InputDecoration(
              labelText: 'Account', border: OutlineInputBorder()),
          items: [
            for (final a in paypalCostAccounts)
              DropdownMenuItem(value: a, child: Text(a)),
          ],
          onChanged: _busy ? null : (v) => setState(() => _account = v),
        ),
        const SizedBox(height: 8),
        DropdownButtonFormField<String>(
          initialValue: paypalPurchaseVatCodes.contains(_vat) ? _vat : 'N',
          isExpanded: true,
          decoration: const InputDecoration(
              labelText: 'VAT', border: OutlineInputBorder()),
          items: [
            for (final c in paypalPurchaseVatCodes)
              DropdownMenuItem(
                  value: c, child: Text(paypalVatLabels[c] ?? c)),
          ],
          onChanged: _busy ? null : (v) => setState(() => _vat = v),
        ),
      ],
      const SizedBox(height: 10),
      Wrap(
        alignment: WrapAlignment.end,
        spacing: 8,
        runSpacing: 8,
        children: [
          OutlinedButton(
            key: Key('reject-${i.transactionId}'),
            style: OutlinedButton.styleFrom(minimumSize: const Size(48, 48)),
            onPressed: _busy ? null : _reject,
            child: const Text('Reject'),
          ),
          FilledButton(
            key: Key('approve-${i.transactionId}'),
            style: FilledButton.styleFrom(
                backgroundColor: AccnomosColors.teal,
                minimumSize: const Size(48, 48)),
            onPressed: _canApprove ? _approve : null,
            child: Text(_busy ? 'Posting…' : 'Approve ${gbp(_gross)}'),
          ),
        ],
      ),
      if (_error != null)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(_error!, style: panelWarn),
        ),
    ]);
  }
}

/// PayPal connected or not. Connecting needs PayPal's own sign-in page and a
/// redirect back to Accnomos, so it happens on the web.
class PayPalConnectionCard extends StatelessWidget {
  const PayPalConnectionCard({super.key, required this.status});

  /// Null: the runtime lists no PayPal at all.
  final PayProviderStatus? status;

  @override
  Widget build(BuildContext context) {
    final s = status;
    final connected = s?.connected ?? false;
    return PanelCard(children: [
      Row(children: [
        Icon(connected ? Icons.check_circle_outline : Icons.link_off_outlined,
            color: connected ? AccnomosColors.posText : AccnomosColors.muted),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            connected ? 'PayPal connected' : 'PayPal is not connected',
            key: const Key('paypal-connection'),
            style: panelTitle,
          ),
        ),
      ]),
      if (connected && (s?.account != null || s?.connectedAt != null))
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(
            [
              if (s?.account != null) s!.account!,
              if (s?.connectedAt != null)
                'since ${ukDate(s!.connectedAt!)}',
              if (s?.testMode ?? false) 'PayPal sandbox: no real money moves',
            ].join(' · '),
            style: panelMuted,
          ),
        ),
      if (!connected && s?.reason != null && !(s?.available ?? true))
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(s!.reason!, style: panelMuted),
        ),
      if (!connected)
        const WebOnlyCard(
          message:
              'Connecting PayPal signs you in on PayPal\'s own page and returns '
              'to Accnomos in the browser, so it is done in Settings › Online '
              'payments on the web.',
          page: '/settings#settings-payments',
        ),
    ]);
  }
}

/// "Is my PayPal money in my books?": PayPal's balance (with its refresh
/// time) against 1240 PayPal clearing, the difference explained as waiting
/// for approval + not posted (+ unexplained, loudly). Read-only.
class PayPalTieOutCard extends StatelessWidget {
  const PayPalTieOutCard({super.key, required this.tie});

  final PayPalTieOut tie;

  @override
  Widget build(BuildContext context) {
    final t = tie;
    final unexplained = t.unexplainedPence ?? 0;
    return Semantics(
      label: 'PayPal and your books',
      child: PanelCard(warn: !t.ties, children: [
        const Text('PayPal and your books', style: panelTitle),
        const SizedBox(height: 6),
        _row('PayPal says', gbp(t.paypalPence ?? 0)),
        if (t.paypalAsOf != null)
          Text('as of ${ukDateTime(t.paypalAsOf!)} (PayPal refreshes this in batches)',
              key: const Key('tie-as-of'),
              style: panelMuted.copyWith(fontSize: 13)),
        _row('Your books (1240 PayPal clearing)', gbp(t.booksPence)),
        const Divider(height: 16),
        _row('Difference', gbp(t.differencePence ?? 0)),
        _row('Waiting for your approval', gbp(t.waitingPence)),
        _row('Not posted (withdrawals, refunds, opening balance and the like)',
            gbp(t.notPostedPence)),
        if (unexplained != 0)
          _row('Unexplained', gbp(unexplained), warn: true),
        for (final n in t.notes)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(n, style: panelMuted.copyWith(fontSize: 13)),
          ),
      ]),
    );
  }

  Widget _row(String label, String value, {bool warn = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
                child: Text(label, style: warn ? panelWarn : null)),
            const SizedBox(width: 8),
            Text(value,
                style: warn
                    ? panelWarn
                    : const TextStyle(fontWeight: FontWeight.w800)),
          ],
        ),
      );
}
