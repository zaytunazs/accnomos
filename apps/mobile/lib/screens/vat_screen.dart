import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/vat_return.dart';
import '../services/auth.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/web_only.dart';
import 'settings_screen.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);

/// VAT return for a period (the current one unless picked): the 9 boxes from
/// `GET /books/vat`, computed by code from the user's own ledger events. The
/// picker lists `GET /books/vat/periods`; the phone does no VAT maths.
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

  @override
  void initState() {
    super.initState();
    _load();
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
      final user = _account?.username ?? settings.userEmail;
      final client = RuntimeClient(
        settings,
        books: BooksAuth(
          graphToken: token,
          accountKind: _auth.kind == AccountKind.work ? 'work' : 'personal',
          user: (user != null && user.isNotEmpty) ? user : null,
          businessName: settings.businessName,
        ),
      );
      final results = await Future.wait([
        client.vat(period: _picked),
        if (withPeriods || _periods.isEmpty) client.vatPeriods(),
      ]);
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
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          'VAT return',
          style: Theme.of(context).textTheme.headlineSmall,
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
                      borderRadius: BorderRadius.circular(14))),
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
                    borderRadius: BorderRadius.circular(14)),
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
            border: Border.all(color: const Color(0xFFE3E1D8)),
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
              for (final box in vat.boxes) _boxRow(box),
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
        const WebOnlyCard(
          message:
              'Filing to HMRC (sandbox connect, obligations, declaration and submit) happens on the web.',
          page: '/vat',
        ),
      ],
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
              _picked = pick.current ? null : period;
              _reload(withPeriods: false);
            },
    );
  }

  Widget _boxRow(VatBox box) {
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
                Text(box.label,
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
            '£${box.amount}',
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
