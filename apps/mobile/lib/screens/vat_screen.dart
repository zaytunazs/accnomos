import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/vat_return.dart';
import '../services/auth.dart';
import '../services/books_events.dart';
import '../services/graph.dart';
import '../services/hmrc.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/brand.dart';
import '../widgets/hmrc_filing.dart';
import 'settings_screen.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);

/// VAT return for a period (the current one unless picked): the 9 boxes from
/// `GET /books/vat`, computed by code from the user's own ledger events. The
/// picker lists `GET /books/vat/periods`; the phone does no VAT maths. Below
/// the boxes, [HmrcFilingCard] connects to HMRC (sandbox), lists HMRC's
/// periods, takes the legal declaration and submits the return, as the web.
class VatScreen extends StatefulWidget {
  const VatScreen({super.key});

  @override
  State<VatScreen> createState() => _VatScreenState();
}

class _VatScreenState extends State<VatScreen> {
  final AuthService _auth = AuthService();
  AppSettings? _settings;
  Account? _account;
  bool _authChecked = false;
  bool _loading = false;
  String? _error;
  VatReturn? _vat;
  List<VatPeriod> _periods = const [];
  String? _picked; // null: the current period
  bool _chosen = false; // the first load picks the period that is due next
  int _seenChange = BooksEvents.changed.value;
  RuntimeClient? _client;
  String? _token;
  Hmrc? _hmrc;
  final GraphService _graph = GraphService();

  @override
  void initState() {
    super.initState();
    BooksEvents.changed.addListener(_onBooksChanged);
    _load();
  }

  @override
  void dispose() {
    BooksEvents.changed.removeListener(_onBooksChanged);
    super.dispose();
  }

  /// An approval (or any other change) elsewhere: the boxes may have moved.
  void _onBooksChanged() {
    if (BooksEvents.changed.value == _seenChange) return;
    _seenChange = BooksEvents.changed.value;
    if (mounted && _vat != null) _reload();
  }

  /// The period the VAT tab opens on: the runtime's `due_period` hint when it
  /// sends one, else the earliest period still open that is not the current
  /// one (the return Home counts down to), else the current period (null).
  static String? duePeriod(Map<String, dynamic> json, List<VatPeriod> periods) {
    final hint = (json['due_period'] ?? '').toString();
    if (hint.isNotEmpty && periods.any((p) => p.period == hint)) return hint;
    final open = periods.where((p) => p.status == 'open' && !p.current).toList()
      ..sort((a, b) => a.start.compareTo(b.start));
    return open.isEmpty ? null : open.first.period;
  }

  String _friendly(Object e) => e.toString().replaceFirst('Exception: ', '');

  Future<void> _load() async {
    final settings = await AppSettings.load();
    Account? account;
    try {
      account = await _auth.account();
    } catch (_) {
      // No account (or no MSAL on this platform): signed-out fallback.
      account = null;
    }
    if (!mounted) return;
    setState(() {
      _settings = settings;
      _account = account;
      _authChecked = true;
    });
    if (account != null) await _reload();
  }

  /// The boxes, and the period list too unless only the pick changed.
  Future<void> _reload({bool withPeriods = true}) async {
    final settings = _settings;
    if (settings == null || _account == null || _loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final token = await _auth.token();
      _token = token;
      final user = _account?.username ?? settings.userEmail;
      final client = _client = RuntimeClient(
        settings,
        books: BooksAuth(
          graphToken: token,
          accountKind: _auth.kind == AccountKind.work ? 'work' : 'personal',
          user: (user != null && user.isNotEmpty) ? user : null,
          businessName: settings.businessName,
        ),
      );
      var fetchPeriods = withPeriods || _periods.isEmpty;
      if (!_chosen && _picked == null) {
        final json = await client.vatPeriods();
        _periods = VatPeriod.listFromJson(json);
        _picked = duePeriod(json, _periods);
        _chosen = true;
        fetchPeriods = false;
      }
      final results = await Future.wait([
        client.vat(period: _picked),
        if (fetchPeriods) client.vatPeriods(),
      ]);
      _hmrc ??= Hmrc(relayUrl: settings.runtimeUrl);
      final vat = VatReturn.fromJson(results[0]);
      if (results.length > 1) _periods = VatPeriod.listFromJson(results[1]);
      if (!mounted) return;
      setState(() => _vat = vat);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        leading: const BrandLeading(),
        title: Text(
          'VAT return',
        ),
        actions: [
          if (_account != null)
            IconButton(
              icon: _loading
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.refresh_outlined),
              tooltip: 'Reload VAT return',
              constraints:
                  const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : _reload,
            ),
        ],
      ),
      body: !_authChecked || _loading && _vat == null
          ? const Center(child: CircularProgressIndicator())
          : _account == null
              ? _signedOut()
              : _vat == null
                  ? _errorView()
                  : _returnView(_vat!),
    );
  }

  Widget _signedOut() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 56,
              height: 56,
              decoration: BoxDecoration(
                  color: AccnomosColors.tealTint,
                  borderRadius: BorderRadius.circular(16)),
              child: const Icon(Icons.receipt_long_outlined,
                  color: AccnomosColors.tealDark),
            ),
            const SizedBox(height: 14),
            Text('Your VAT return lives in your books',
                style: Theme.of(context).textTheme.titleMedium,
                textAlign: TextAlign.center),
            const SizedBox(height: 6),
            const Text(
              'Sign in with Microsoft to see the 9 boxes for this period.',
              textAlign: TextAlign.center,
              style: TextStyle(color: AccnomosColors.muted, height: 1.4),
            ),
            const SizedBox(height: 16),
            FilledButton(
              style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size.fromHeight(52),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12))),
              onPressed: () => Navigator.of(context)
                  .push(
                    MaterialPageRoute(
                        builder: (_) => const SettingsScreen()),
                  )
                  .then((_) => _load()),
              child: const Text('Open settings to sign in',
                  style: TextStyle(
                      fontWeight: FontWeight.w800, fontSize: 16)),
            ),
          ],
        ),
      ),
    );
  }

  Widget _errorView() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              _error ?? 'Could not load the VAT return.',
              textAlign: TextAlign.center,
              style: const TextStyle(color: _warnInk, height: 1.4),
            ),
            const SizedBox(height: 16),
            OutlinedButton(
              style: OutlinedButton.styleFrom(
                minimumSize: const Size.fromHeight(48),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12)),
              ),
              onPressed: _reload,
              child: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _returnView(VatReturn vat) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: AccnomosColors.border),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (_periods.isNotEmpty) ...[
                _periodPicker(vat),
                const SizedBox(height: 10),
              ],
              Text(
                vat.label.isEmpty
                    ? 'Period ${vat.periodKey}'
                    : '${vat.label}${vat.current ? ' (current)' : ''}'
                        '${vat.submitted ? ' · submitted' : ''}',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 2),
              Text(
                '${_ukDate(vat.start)} – ${_ukDate(vat.end)} · ${vat.eventsInPeriod} entries',
                style: const TextStyle(
                    color: AccnomosColors.muted, height: 1.4),
              ),
              const Divider(height: 24),
              for (final box in vat.boxes) _boxRow(vat, box),
            ],
          ),
        ),
        if (vat.warnings.isNotEmpty)
          Container(
            width: double.infinity,
            margin: const EdgeInsets.only(top: 12),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: _warnBg,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: _warnBorder),
            ),
            child: Text(
              vat.warnings.join('\n'),
              style: const TextStyle(color: _warnInk, height: 1.4),
            ),
          ),
        if (_error != null) ...[
          const SizedBox(height: 12),
          Text(_error!,
              style: const TextStyle(color: _warnInk, height: 1.4)),
        ],
        const SizedBox(height: 12),
        const Text(
          'Calculated by code from your ledger — never by a model.',
          textAlign: TextAlign.center,
          style: TextStyle(color: AccnomosColors.muted, fontSize: 12),
        ),
        if (_hmrc != null && _client != null && _token != null)
          HmrcFilingCard(
            vat: vat,
            periods: _periods,
            deps: _filingDeps(),
            onPickPeriod: (period) {
              if (period == _picked && period != null) return;
              _picked = period;
              _reload(withPeriods: false);
            },
          ),
      ],
    );
  }

  VatFilingDeps _filingDeps() {
    final client = _client!;
    final token = _token!;
    final kind = _auth.kind;
    return VatFilingDeps(
      hmrc: _hmrc!,
      accountId: _account?.id,
      businessVat: _settings?.vatNumber,
      postObligations: (list) => client.postVatObligations(list),
      saveFile: (relPath, text) async {
        final folder = relPath.substring(0, relPath.lastIndexOf('/'));
        await _graph.ensureFolder(token, kind, vatReturnsFolder);
        await _graph.ensureFolder(token, kind, folder);
        await _graph.putFileBytes(
          token: token,
          kind: kind,
          relPath: relPath,
          bytes: utf8.encode(text),
          contentType: 'application/json',
        );
      },
      listReceipts: () async {
        final kids = await _graph.listChildren(token, kind, vatReturnsFolder);
        final folders = [for (final k in kids) if (k.isFolder) k.name]..sort();
        final rows = <(String, bool)>[];
        for (final name in folders.reversed.take(9)) {
          try {
            final inner = await _graph.listChildren(token, kind, '$vatReturnsFolder/$name');
            rows.add((name, inner.any((f) => f.name == 'receipt.json')));
          } catch (_) {
            rows.add((name, false));
          }
        }
        return rows;
      },
    );
  }

  Widget _periodPicker(VatReturn vat) {
    final value = _periods.any((p) => p.period == vat.period)
        ? vat.period
        : _periods.first.period;
    return DropdownButtonFormField<String>(
      key: ValueKey(value),
      initialValue: value,
      isExpanded: true,
      decoration: const InputDecoration(
        labelText: 'VAT period',
        border: OutlineInputBorder(),
      ),
      items: [
        for (final p in _periods)
          DropdownMenuItem(
            value: p.period,
            child: Text(p.caption, overflow: TextOverflow.ellipsis),
          ),
      ],
      onChanged: _loading
          ? null
          : (period) {
              if (period == null || period == vat.period) return;
              final pick = _periods.firstWhere((p) => p.period == period);
              _picked = pick.period;
              _reload(withPeriods: false);
            },
    );
  }

  Widget _boxRow(VatReturn vat, VatBox box) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 7),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 30,
            height: 30,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: AccnomosColors.tealTint,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              '${box.box}',
              style: const TextStyle(
                  fontWeight: FontWeight.w800,
                  color: AccnomosColors.tealDark),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(vat.labelFor(box),
                    style: const TextStyle(
                        color: AccnomosColors.ink,
                        fontWeight: FontWeight.w700)),
                Text(
                  '${box.entries} ${box.entries == 1 ? 'entry' : 'entries'}',
                  style: const TextStyle(
                      color: AccnomosColors.muted, fontSize: 12),
                ),
              ],
            ),
          ),
          Text(
            vat.displayFor(box),
            style: const TextStyle(
                color: AccnomosColors.ink,
                fontWeight: FontWeight.w800,
                fontSize: 16),
          ),
        ],
      ),
    );
  }

  static String _ukDate(String iso) {
    final text = iso.trim();
    if (text.isEmpty) return '—';
    try {
      final d = DateTime.parse(text);
      const months = [
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
      ];
      return '${d.day} ${months[d.month - 1]} ${d.year}';
    } catch (_) {
      return text;
    }
  }
}
