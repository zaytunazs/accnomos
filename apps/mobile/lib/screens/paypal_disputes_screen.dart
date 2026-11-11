import 'package:flutter/material.dart';

import '../models/paypal.dart';
import '../services/books.dart';
import '../services/runtime_client.dart';
import '../theme.dart';
import '../widgets/web_only.dart';
import 'paypal_common.dart';

/// Invoices › PayPal disputes, as the web's Disputes panel: disputes on
/// payments Accnomos knows about, evidence built from the books (the
/// response previewed here), sent to PayPal only when the owner taps Send
/// and says yes. A lost dispute offers the reversing entry, again only on
/// the owner's yes. The evidence PDF itself opens on the web.
class PayPalDisputesScreen extends StatefulWidget {
  const PayPalDisputesScreen({super.key, this.clientFactory});

  final PayPalClientFactory? clientFactory;

  @override
  State<PayPalDisputesScreen> createState() => _PayPalDisputesScreenState();
}

class _PayPalDisputesScreenState extends State<PayPalDisputesScreen> {
  RuntimeClient? _client;
  bool _ready = false;
  bool _loading = false;
  String? _error;
  PayPalDisputeList? _list;

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
      final list = await client.paypalDisputes();
      if (mounted) setState(() => _list = list);
    } catch (e) {
      if (mounted) setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        title: const Text('PayPal disputes'),
        actions: [
          if (_client != null)
            IconButton(
              icon: const Icon(Icons.refresh_outlined),
              tooltip: 'Reload disputes',
              constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : _reload,
            ),
        ],
      ),
      body: !_ready || (_loading && _list == null)
          ? const Center(child: CircularProgressIndicator())
          : _client == null
              ? const PayPalSignedOut(what: 'see PayPal disputes')
              : RefreshIndicator(onRefresh: _reload, child: _body()),
    );
  }

  Widget _body() {
    final list = _list;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
      children: [
        const Text(
          'Accnomos builds the evidence from your books: the invoice as it was '
          'emailed, when it was sent and paid, the work logged and the audit '
          'trail. Nothing goes to PayPal until you press Send.',
          style: panelMuted,
        ),
        const SizedBox(height: 12),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(_error!, style: panelWarn),
          ),
        if (list?.problem != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(list!.problem!, style: panelWarn),
          ),
        if (list != null && list.disputes.isEmpty && list.problem == null)
          PanelCard(children: [
            Text(
              list.connected
                  ? 'No PayPal disputes. Good.'
                  : 'No PayPal disputes. Connect PayPal on the web to have them checked here.',
              key: const Key('disputes-empty'),
              style: panelMuted,
            ),
          ]),
        if (list != null)
          for (final d in list.disputes)
            DisputeCard(
              key: ValueKey('dispute-${d.disputeId}'),
              dispute: d,
              client: _client!,
              onChanged: _reload,
            ),
        const WebOnlyCard(
          message:
              'The evidence PDF opens, downloads and can be checked page by '
              'page on the web; the phone shows the response PayPal gets.',
          page: '/invoices',
        ),
      ],
    );
  }
}

class DisputeCard extends StatefulWidget {
  const DisputeCard({
    super.key,
    required this.dispute,
    required this.client,
    required this.onChanged,
  });

  final PayPalDispute dispute;
  final RuntimeClient client;
  final Future<void> Function() onChanged;

  @override
  State<DisputeCard> createState() => _DisputeCardState();
}

class _DisputeCardState extends State<DisputeCard> {
  late DisputeEvidence? _proposal = widget.dispute.proposal;
  String? _busy;
  String? _error;
  String? _note;

  PayPalDispute get d => widget.dispute;

  Future<void> _act(String kind, Future<void> Function() run) async {
    setState(() {
      _busy = kind;
      _error = null;
    });
    try {
      await run();
    } catch (e) {
      if (mounted) setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  Future<void> _build() => _act('build', () async {
        final p = await widget.client.buildDisputeEvidence(d.disputeId);
        if (mounted) setState(() => _proposal = p);
      });

  Future<void> _send() async {
    final yes = await confirmAction(
      context,
      title: 'Send this evidence to PayPal?',
      body: d.sample
          ? 'This is the demo\'s sample dispute: it is recorded as sent and '
              'nothing goes to PayPal.'
          : 'PayPal gets the response shown and the evidence PDF for '
              '${d.invoice ?? 'this payment'}. You cannot take it back.',
      yes: 'Send to PayPal',
    );
    if (!yes) return;
    await _act('send', () async {
      final out = await widget.client.sendDisputeEvidence(d.disputeId);
      if (!mounted) return;
      setState(() {
        _proposal = out;
        _note = out.demo
            ? 'Demo: recorded as sent. Nothing was sent to PayPal.'
            : 'Evidence sent to PayPal.';
      });
      await widget.onChanged();
    });
  }

  Future<void> _reverse(DisputeReversal r) async {
    final yes = await confirmAction(
      context,
      title: 'Post the reversing entry?',
      body: 'Takes the PayPal payment of ${gbp(r.amountPence)} back out of '
          'your books; ${d.invoice ?? 'the invoice'} is then open again.',
      yes: 'Post ${gbp(r.amountPence)}',
    );
    if (!yes) return;
    await _act('reverse', () async {
      await widget.client.postDisputeReversal(d.disputeId);
      if (mounted) {
        setState(() =>
            _note = 'Payment taken back; ${d.invoice ?? 'the invoice'} is open again.');
      }
      await widget.onChanged();
    });
  }

  @override
  Widget build(BuildContext context) {
    final p = _proposal;
    final sent = p?.sent ?? false;
    final reversal = d.reversal;
    return PanelCard(warn: d.waitingForYou, children: [
      if (d.sample)
        const Padding(
          padding: EdgeInsets.only(bottom: 4),
          child: Text('SAMPLE (DEMO)', style: panelWarn),
        ),
      Text(
        '${d.invoice != null ? '${d.invoice} · ${d.customer ?? ''}' : 'Not a payment Accnomos knows about'}'
        '${d.amountPence != null ? ' · ${gbp(d.amountPence!)} disputed' : ''}',
        style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15),
      ),
      const SizedBox(height: 4),
      Text(
        [
          'The customer ${d.reasonText}.',
          d.statusLabel,
          if (d.respondBy != null && d.waitingForYou)
            'answer by ${ukDate(d.respondBy!)}',
          if (d.opened != null) 'opened ${ukDate(d.opened!)}',
          'PayPal ${d.disputeId}',
        ].join(' · '),
        style: panelMuted,
      ),
      if (d.invoice == null)
        const Padding(
          padding: EdgeInsets.only(top: 6),
          child: Text(
              'Answer this one in PayPal: Accnomos has no record of the payment.'),
        ),
      if (d.canSendEvidence && !sent && p == null)
        Padding(
          padding: const EdgeInsets.only(top: 10),
          child: FilledButton(
            key: Key('build-${d.disputeId}'),
            style: FilledButton.styleFrom(
                backgroundColor: AccnomosColors.teal,
                minimumSize: const Size(48, 48)),
            onPressed: _busy != null ? null : _build,
            child: Text(_busy == 'build' ? 'Building the evidence…' : 'Build evidence'),
          ),
        ),
      if (p != null)
        Container(
          width: double.infinity,
          margin: const EdgeInsets.only(top: 10),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
              color: AccnomosColors.ground,
              borderRadius: BorderRadius.circular(10)),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(sent ? 'Sent to PayPal' : 'Response for PayPal (preview)',
                  style: const TextStyle(fontWeight: FontWeight.w800)),
              const SizedBox(height: 6),
              Text(p.notes, key: Key('evidence-${d.disputeId}')),
              const SizedBox(height: 6),
              Text(
                p.fallbackReason != null
                    ? 'Written by code from your books. ${p.fallbackReason}'
                    : 'Drafted by the AI; every figure and date checked against your books.',
                style: panelMuted.copyWith(fontSize: 13),
              ),
              if (sent && p.sentAt != null)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    '${p.demo ? 'Demo: not sent to PayPal. ' : ''}'
                    'Sent ${ukDate(p.sentAt!)}${p.sentBy != null ? ' by ${p.sentBy}' : ''}.',
                    style: panelMuted.copyWith(fontSize: 13),
                  ),
                ),
              if (!sent && d.canSendEvidence)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Wrap(spacing: 8, runSpacing: 8, children: [
                    OutlinedButton(
                      style: OutlinedButton.styleFrom(
                          minimumSize: const Size(48, 48)),
                      onPressed: _busy != null ? null : _build,
                      child: const Text('Build again'),
                    ),
                    FilledButton(
                      key: Key('send-${d.disputeId}'),
                      style: FilledButton.styleFrom(
                          backgroundColor: AccnomosColors.teal,
                          minimumSize: const Size(48, 48)),
                      onPressed: _busy != null ? null : _send,
                      child: Text(_busy == 'send'
                          ? 'Sending…'
                          : d.sample
                              ? 'Send to PayPal (demo)'
                              : 'Send to PayPal'),
                    ),
                  ]),
                ),
            ],
          ),
        ),
      if (d.lost && reversal != null)
        Container(
          width: double.infinity,
          margin: const EdgeInsets.only(top: 10),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
              border: Border.all(color: AccnomosColors.border),
              borderRadius: BorderRadius.circular(10)),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('PayPal found for the customer: take the payment back?',
                  style: TextStyle(fontWeight: FontWeight.w800)),
              JournalPreview(lines: reversal.journal),
              const SizedBox(height: 4),
              const Text(
                  'The invoice is then open again: raise a credit note or chase it, as you decide.',
                  style: panelMuted),
              const SizedBox(height: 8),
              if (reversal.canPost)
                FilledButton(
                  key: Key('reverse-${d.disputeId}'),
                  style: FilledButton.styleFrom(
                      backgroundColor: AccnomosColors.teal,
                      minimumSize: const Size(48, 48)),
                  onPressed: _busy != null ? null : () => _reverse(reversal),
                  child: Text(_busy == 'reverse'
                      ? 'Posting…'
                      : 'Post reversing entry for ${gbp(reversal.amountPence)}'),
                )
              else if (reversal.reason != null)
                Text(reversal.reason!, style: panelWarn),
            ],
          ),
        ),
      if (_note != null)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(_note!,
              style: const TextStyle(
                  fontWeight: FontWeight.w700, color: AccnomosColors.tealDark)),
        ),
      if (_error != null)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(_error!, style: panelWarn),
        ),
    ]);
  }
}
