import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models/vat_return.dart';
import '../services/demo.dart';
import '../services/hmrc.dart';
import '../theme.dart';

/// What the filing card needs from the screen around it, so it can be tested
/// without a phone, a Microsoft account or HMRC.
class VatFilingDeps {
  VatFilingDeps({
    required this.hmrc,
    required this.accountId,
    required this.businessVat,
    required this.postObligations,
    required this.saveFile,
    required this.listReceipts,
  });

  final Hmrc hmrc;
  final String? accountId;
  final String? businessVat;

  /// POST /books/vat/obligations (skipped in a demo: its list is made up).
  final Future<void> Function(List<Map<String, dynamic>> obligations) postObligations;

  /// Write a small JSON file into the books (`06 VAT returns/<period>/...`).
  final Future<void> Function(String relPath, String json) saveFile;

  /// Earlier submissions: (period folder, has receipt.json), newest first.
  final Future<List<(String, bool)>> Function() listReceipts;
}

const vatReturnsFolder = '06 VAT returns';

/// "Connect to HMRC (sandbox)": OAuth via the relay, HMRC's obligations, the
/// legal declaration, the submission of the return computed by code, and
/// HMRC's receipt — the phone's twin of the web's ConnectHmrc.tsx.
class HmrcFilingCard extends StatefulWidget {
  const HmrcFilingCard({
    super.key,
    required this.vat,
    required this.deps,
    required this.onPickPeriod,
    this.periods = const [],
  });

  /// The return shown above (the figures that would be sent).
  final VatReturn vat;
  final List<VatPeriod> periods;
  final VatFilingDeps deps;

  /// Show the books' period whose dates match an obligation (null: current).
  final void Function(String? period) onPickPeriod;

  @override
  State<HmrcFilingCard> createState() => _HmrcFilingCardState();
}

enum _Step { list, submitting, done }

class _HmrcFilingCardState extends State<HmrcFilingCard> with WidgetsBindingObserver {
  final _vrn = TextEditingController();
  final _scenario = TextEditingController();
  bool _connected = false;
  bool _busy = false;
  String? _error;
  List<Obligation>? _obligations;
  String? _selected;
  List<String> _missing = const [];
  bool _declared = false;
  _Step _step = _Step.list;
  RelayResult? _result;
  String? _saved; // null saving, 'saved', or the reason it could not save
  List<(String, bool)>? _receipts;

  bool get _demo => Demo.active;
  Hmrc get _hmrc => widget.deps.hmrc;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _connected = _hmrc.connected;
    _init();
  }

  Future<void> _init() async {
    final v = await _hmrc.savedVrn(widget.deps.businessVat);
    if (mounted && _vrn.text.isEmpty) _vrn.text = v;
    await _takeCallback();
    if (_connected) _loadReceipts();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _vrn.dispose();
    _scenario.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _takeCallback();
  }

  @override
  void didUpdateWidget(HmrcFilingCard old) {
    super.didUpdateWidget(old);
    // New figures above: a half-made declaration may be for the previous ones.
    if (old.vat.period != widget.vat.period && _step != _Step.done) _declared = false;
  }

  /// HMRC's answer, handed back to the app after the browser sign-in.
  Future<void> _takeCallback() async {
    final cb = await _hmrc.takeCallback();
    if (cb == null || !mounted) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await _hmrc.finishConnect(cb);
      if (!mounted) return;
      setState(() => _connected = true);
      _loadReceipts();
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _connect() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await _hmrc.startConnect();
      if (_demo && mounted) {
        setState(() => _connected = true); // simulated: no HMRC page to go to
        _loadReceipts();
      }
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _disconnect() {
    Hmrc.disconnect();
    setState(() {
      _connected = false;
      _obligations = null;
      _selected = null;
      _step = _Step.list;
      _result = null;
      _error = null;
      _declared = false;
    });
  }

  void _fail(Object e) {
    if (e is HmrcAuthException) {
      _connected = false;
      _obligations = null;
      _step = _Step.list;
    }
    _error = e.toString();
  }

  bool get _vrnOk => RegExp(r'^\d{9}$').hasMatch(cleanVrn(_vrn.text));

  Future<void> _loadObligations() async {
    if (!_vrnOk) return;
    final v = cleanVrn(_vrn.text);
    setState(() {
      _busy = true;
      _error = null;
      _step = _Step.list;
      _result = null;
    });
    try {
      await _hmrc.rememberVrn(v);
      final to = DateTime.now();
      final res = await _hmrc.obligations(v,
          accountId: widget.deps.accountId,
          from: to.subtract(const Duration(days: 365)),
          to: to,
          scenario: _scenario.text);
      final list = Obligation.listFrom(res.hmrc);
      if (!_demo) {
        try {
          await widget.deps.postObligations([for (final o in list) o.toJson()]);
        } catch (_) {
          // The period list just won't know about HMRC's list yet; HMRC's own list below still stands.
        }
      }
      final vat = widget.vat;
      Obligation? match;
      for (final o in list) {
        if (o.open && o.start == vat.start && o.end == vat.end) match = o;
      }
      match ??= list.where((o) => o.open).firstOrNull;
      if (!mounted) return;
      setState(() {
        _obligations = list;
        _missing = res.missing;
        _selected = match?.periodKey;
      });
      if (match != null) _showPeriodFor(match);
    } catch (e) {
      if (mounted) setState(() => _fail(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Show the books' period with the obligation's dates above, if there is one.
  void _showPeriodFor(Obligation o) {
    if (widget.vat.start == o.start && widget.vat.end == o.end) return;
    for (final p in widget.periods) {
      if (p.start == o.start && p.end == o.end) {
        widget.onPickPeriod(p.current ? null : p.period);
        return;
      }
    }
  }

  Obligation? get _obligation =>
      _obligations?.where((o) => o.periodKey == _selected).firstOrNull;

  /// Why Submit is not available, or null when it is.
  String? get _blocked {
    final o = _obligation;
    final vat = widget.vat;
    if (o == null) return 'Pick an open period from HMRC above.';
    if (!o.open) return 'HMRC already has a return for this period.';
    if (vat.start != o.start || vat.end != o.end) {
      return "The return above is for ${vat.start} to ${vat.end}; HMRC's period is ${o.start} to ${o.end}. "
          'Pick the matching period at the top.';
    }
    if (!vat.canSubmit) return 'This period cannot be submitted from your books yet (it may be submitted already).';
    if (vat.hmrcBody.isEmpty) return 'The return has no figures to send.';
    return null;
  }

  Future<void> _submit() async {
    final o = _obligation;
    if (o == null || _blocked != null || !_declared) return;
    final v = cleanVrn(_vrn.text);
    final body = toReturnBody(widget.vat.hmrcBody, o.periodKey);
    setState(() {
      _error = null;
      _step = _Step.submitting;
    });
    try {
      final res = await _hmrc.submit(v, body, accountId: widget.deps.accountId, scenario: _scenario.text);
      if (!mounted) return;
      final next = [for (final x in _obligations ?? <Obligation>[]) x.periodKey == o.periodKey ? x.fulfilled() : x];
      setState(() {
        _result = res;
        _missing = res.missing;
        _step = _Step.done;
        _obligations = next;
        _saved = null;
      });
      if (!_demo) {
        try {
          await widget.deps.postObligations([for (final x in next) x.toJson()]);
        } catch (_) {
          // the receipt below is the record that matters
        }
      }
      await _saveRecords(v, o, body, res);
    } catch (e) {
      if (mounted) {
        setState(() {
          _step = _Step.list;
          _fail(e);
        });
      }
    }
  }

  Future<void> _saveRecords(String vrn, Obligation o, Map<String, dynamic> body, RelayResult res) async {
    final vat = widget.vat;
    final folder = '$vatReturnsFolder/${o.periodKey}';
    final at = DateTime.now().toUtc().toIso8601String();
    const pretty = JsonEncoder.withIndent('  ');
    try {
      await widget.deps.saveFile(
        '$folder/return.json',
        pretty.convert({
          'vrn': vrn,
          'periodKey': o.periodKey,
          'obligation': {'start': o.start, 'end': o.end, 'due': o.due},
          'calculated_for': {'period_key': vat.periodKey, 'start': vat.start, 'end': vat.end},
          'calculated_by': 'code (packages/ledger compute_vat_return) from approved ledger events',
          'return': body,
          'event_ids': vat.eventIds,
          'warnings': vat.warnings,
          'declaration': vatDeclaration,
          'declared_at': at,
          'environment': _demo ? demoSubmission : 'HMRC sandbox',
          'sent_from': 'Accnomos Android app',
        }),
      );
      await widget.deps.saveFile(
        '$folder/receipt.json',
        pretty.convert({
          'vrn': vrn,
          'periodKey': o.periodKey,
          'submitted_at': at,
          'environment': _demo ? '$demoSubmission: HMRC was not contacted' : 'HMRC sandbox',
          'hmrc': res.hmrc,
          'correlation_id': res.correlationId,
          'receipt_id': res.receiptId,
          'receipt_timestamp': res.receiptTimestamp,
          'sent_headers': res.sentHeaders,
          'fraud_headers_missing': res.missing,
        }),
      );
      if (mounted) setState(() => _saved = 'saved');
      _loadReceipts();
    } catch (e) {
      if (mounted) {
        setState(() => _saved = "Couldn't save to your books: $e. The submission itself went through — note the receipt below.");
      }
    }
  }

  Future<void> _loadReceipts() async {
    try {
      final rows = await widget.deps.listReceipts();
      if (mounted) setState(() => _receipts = rows);
    } catch (_) {
      if (mounted) setState(() => _receipts = const []);
    }
  }

  // --- view ---------------------------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AccnomosColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text('Connect to HMRC', style: Theme.of(context).textTheme.titleMedium),
              ),
              _chip(_demo ? 'Demo — HMRC simulated' : 'Sandbox', _demo ? _amberBg : AccnomosColors.tealTint,
                  _demo ? _amberInk : AccnomosColors.tealDark),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            _demo
                ? 'In the demo nothing reaches HMRC: connecting, the periods and the submission are simulated, and the receipt says so.'
                : 'Nothing is sent until you tick the legal declaration and press Submit. The return and HMRC\'s receipt are then saved to $vatReturnsFolder in your books.',
            style: const TextStyle(color: AccnomosColors.muted, height: 1.4),
          ),
          const SizedBox(height: 12),
          _stepsStrip(),
          if (_error != null) ...[
            const SizedBox(height: 12),
            _notice(_error!, negative: true),
          ],
          const SizedBox(height: 12),
          if (!_connected) ..._disconnectedView() else ..._connectedView(),
        ],
      ),
    );
  }

  Widget _stepsStrip() {
    final at = !_connected
        ? 0
        : _step == _Step.done
            ? 3
            : _obligations == null
                ? 1
                : 2;
    const labels = ['Connect', 'Periods', 'Declare & submit', 'Receipt'];
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        for (var i = 0; i < labels.length; i++)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: i < at ? AccnomosColors.tealTint : i == at ? AccnomosColors.teal : AccnomosColors.ground,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: i == at ? AccnomosColors.teal : AccnomosColors.border),
            ),
            child: Text(
              '${i + 1}. ${labels[i]}${i < at ? ' ✓' : ''}',
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: i == at ? Colors.white : AccnomosColors.ink,
              ),
            ),
          ),
      ],
    );
  }

  List<Widget> _disconnectedView() => [
        FilledButton.icon(
          key: const Key('hmrc-connect'),
          onPressed: _busy ? null : _connect,
          icon: _busy
              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : const Icon(Icons.link),
          label: Text(_demo ? 'Connect (simulated)' : 'Connect to HMRC (sandbox)'),
          style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
        ),
        if (!_demo) ...[
          const SizedBox(height: 8),
          const Text(
            "Opens HMRC's own sign-in page in your browser, then brings you back here. The app keeps the HMRC session only while it is open.",
            style: TextStyle(color: AccnomosColors.muted, fontSize: 13, height: 1.4),
          ),
        ],
      ];

  List<Widget> _connectedView() {
    final out = <Widget>[
      TextField(
        key: const Key('hmrc-vrn'),
        controller: _vrn,
        enabled: !_demo,
        keyboardType: TextInputType.number,
        decoration: const InputDecoration(labelText: 'VAT registration number', hintText: '9 digits'),
        onChanged: (_) => setState(() {}),
      ),
      if (!_demo)
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: const Text('Sandbox test scenario (optional)', style: TextStyle(fontSize: 14)),
            children: [
              TextField(
                controller: _scenario,
                decoration: const InputDecoration(
                  labelText: 'Gov-Test-Scenario',
                  hintText: 'e.g. QUARTERLY_NONE_MET',
                ),
              ),
            ],
          ),
        ),
      const SizedBox(height: 8),
      Row(
        children: [
          Expanded(
            child: FilledButton(
              key: const Key('hmrc-obligations'),
              onPressed: _busy || !_vrnOk ? null : _loadObligations,
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
              child: _busy
                  ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Text('Get VAT periods from HMRC'),
            ),
          ),
          const SizedBox(width: 8),
          OutlinedButton(
            onPressed: _busy ? null : _disconnect,
            style: OutlinedButton.styleFrom(minimumSize: const Size(0, 48)),
            child: const Text('Disconnect'),
          ),
        ],
      ),
    ];
    final obs = _obligations;
    if (obs != null) {
      out.add(const SizedBox(height: 16));
      out.add(Text("HMRC's VAT periods", style: Theme.of(context).textTheme.titleSmall));
      if (obs.isEmpty) {
        out.add(_notice('HMRC has no VAT periods for this number in the last year.'));
      }
      for (final o in obs) {
        out.add(_obligationRow(o));
      }
      if (_missing.isNotEmpty) {
        out.add(_notice('Fraud-prevention headers this phone could not supply: ${_missing.join(', ')}.'));
      }
      if (_step != _Step.done) out.addAll(_declareAndSubmit());
    }
    if (_step == _Step.done && _result != null) out.add(_receipt(_result!));
    final receipts = _receipts;
    if (receipts != null) {
      out.add(const SizedBox(height: 16));
      out.add(Text('Earlier submissions', style: Theme.of(context).textTheme.titleSmall));
      out.add(const SizedBox(height: 4));
      if (receipts.isEmpty) {
        out.add(const Text('No receipts saved yet. After you submit, the return and HMRC\'s receipt are kept in '
            '$vatReturnsFolder.', style: TextStyle(color: AccnomosColors.muted, height: 1.4)));
      }
      for (final (period, saved) in receipts) {
        out.add(Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(children: [
            Icon(saved ? Icons.verified_outlined : Icons.description_outlined,
                size: 18, color: saved ? AccnomosColors.tealDark : AccnomosColors.muted),
            const SizedBox(width: 8),
            Expanded(child: Text('$period · ${saved ? 'receipt saved' : 'return only'}')),
          ]),
        ));
      }
    }
    return out;
  }

  Widget _obligationRow(Obligation o) {
    final picked = o.periodKey == _selected;
    return InkWell(
      key: Key('obligation-${o.periodKey}'),
      borderRadius: BorderRadius.circular(8),
      onTap: !o.open || _step == _Step.submitting
          ? null
          : () {
              setState(() {
                _selected = o.periodKey;
                _declared = false;
              });
              _showPeriodFor(o);
            },
      child: Container(
        margin: const EdgeInsets.only(top: 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: picked ? AccnomosColors.teal : AccnomosColors.border, width: picked ? 2 : 1),
        ),
        child: Row(
          children: [
            Icon(picked ? Icons.radio_button_checked : Icons.radio_button_off,
                color: o.open ? AccnomosColors.teal : AccnomosColors.border),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('${ukDay(o.start)} – ${ukDay(o.end)}', style: const TextStyle(fontWeight: FontWeight.w700)),
                  Text(
                    o.open ? 'Due ${ukDay(o.due)} · period ${o.periodKey}' : 'Received ${ukDay(o.received ?? o.due)}',
                    style: const TextStyle(color: AccnomosColors.muted, fontSize: 13),
                  ),
                ],
              ),
            ),
            _chip(o.open ? 'Open' : 'Fulfilled', o.open ? _amberBg : _greenBg, o.open ? _amberInk : _greenInk),
          ],
        ),
      ),
    );
  }

  List<Widget> _declareAndSubmit() {
    final blocked = _blocked;
    final vat = widget.vat;
    final submitting = _step == _Step.submitting;
    final box5 = vat.boxes.where((b) => b.box == 5).firstOrNull;
    return [
      const SizedBox(height: 16),
      Text('Declare and submit', style: Theme.of(context).textTheme.titleSmall),
      const SizedBox(height: 6),
      if (blocked != null)
        _notice(blocked)
      else ...[
        Text(
          'Sending the 9 boxes above for ${ukDay(vat.start)} – ${ukDay(vat.end)}'
          '${box5 != null ? ' (box 5: ${box5.display})' : ''}, computed by code from your approved entries.',
          style: const TextStyle(height: 1.4),
        ),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: AccnomosColors.ground,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: AccnomosColors.border),
          ),
          child: CheckboxListTile(
            key: const Key('hmrc-declare'),
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            value: _declared,
            onChanged: submitting ? null : (v) => setState(() => _declared = v ?? false),
            title: const Text(vatDeclaration, style: TextStyle(height: 1.4)),
          ),
        ),
      ],
      const SizedBox(height: 10),
      FilledButton(
        key: const Key('hmrc-submit'),
        onPressed: blocked == null && _declared && !submitting ? _submit : null,
        style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
        child: submitting
            ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
            : Text(_demo ? 'Submit (simulated)' : 'Submit to HMRC (sandbox)'),
      ),
    ];
  }

  Widget _receipt(RelayResult res) {
    final r = res.hmrc is Map ? SubmitReceipt.fromJson(Map<String, dynamic>.from(res.hmrc as Map)) : null;
    return Container(
      key: const Key('hmrc-receipt'),
      width: double.infinity,
      margin: const EdgeInsets.only(top: 16),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: _greenBg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFB7E4C7)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(_demo ? demoSubmission : 'Submitted to HMRC (sandbox)',
              style: const TextStyle(fontWeight: FontWeight.w800, color: _greenInk, fontSize: 16)),
          const SizedBox(height: 8),
          if (r != null) ...[
            _receiptRow('Processing date', r.processingDate),
            Row(children: [
              Expanded(child: _receiptRow('Form bundle number', r.formBundleNumber)),
              IconButton(
                tooltip: 'Copy form bundle number',
                icon: const Icon(Icons.copy, size: 18),
                onPressed: () => Clipboard.setData(ClipboardData(text: r.formBundleNumber)),
              ),
            ]),
            if (r.chargeRefNumber != null) _receiptRow('Charge reference', r.chargeRefNumber!),
            if (r.paymentIndicator != null) _receiptRow('Payment indicator', r.paymentIndicator!),
          ],
          if (res.correlationId != null) _receiptRow('Correlation id', res.correlationId!),
          const SizedBox(height: 6),
          Text(
            _saved == null
                ? 'Saving the return and receipt to your books…'
                : _saved == 'saved'
                    ? 'Saved to ${_demo ? "the demo's books" : 'your books'}: $vatReturnsFolder/${_selected ?? ''}/receipt.json and return.json.'
                    : _saved!,
            style: const TextStyle(color: AccnomosColors.muted, fontSize: 13, height: 1.4),
          ),
        ],
      ),
    );
  }

  Widget _receiptRow(String label, String value) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Text.rich(TextSpan(children: [
          TextSpan(text: '$label: ', style: const TextStyle(color: AccnomosColors.muted)),
          TextSpan(text: value, style: const TextStyle(fontWeight: FontWeight.w700)),
        ])),
      );

  Widget _chip(String text, Color bg, Color ink) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(6)),
        child: Text(text, style: TextStyle(color: ink, fontSize: 12, fontWeight: FontWeight.w600)),
      );

  Widget _notice(String text, {bool negative = false}) => Container(
        width: double.infinity,
        margin: const EdgeInsets.only(top: 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: negative ? AccnomosColors.negTint : _amberBg,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(text, style: TextStyle(color: negative ? AccnomosColors.negText : _amberInk, height: 1.4)),
      );
}

const _amberBg = AccnomosColors.warnTint;
const _amberInk = AccnomosColors.warnText;
const _greenBg = AccnomosColors.posTint;
const _greenInk = AccnomosColors.posText;

/// `3 Nov 2026` from an ISO date (as given when it does not parse).
String ukDay(String iso) {
  final d = DateTime.tryParse(iso.trim());
  if (d == null) return iso;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return '${d.day} ${months[d.month - 1]} ${d.year}';
}
