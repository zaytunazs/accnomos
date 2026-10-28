import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/dashboard.dart';
import '../models/suggestions.dart';
import '../services/auth.dart';
import '../services/books.dart' show booksClient;
import '../services/settings.dart';
import '../theme.dart';
import 'bank_screen.dart';
import 'home_cards.dart';
import 'invoices_screen.dart';
import 'review_screen.dart';
import 'sample_books_card.dart';
import 'settings_screen.dart';
import 'vat_screen.dart';

/// Home: tiles from `GET /books/dashboard` when signed in (grey bars while
/// loading, "—" for anything unknown); "Connect to see" when signed out.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final AuthService _auth = AuthService();
  AppSettings? _settings;
  Account? _account;
  bool _loading = false;
  String? _error;
  Dashboard? _data;
  int _refresh = 0;

  /// Opens the screen a dashboard suggestion points at.
  void _openSuggestion(SuggestionTarget target) {
    final screen = switch (target) {
      SuggestionTarget.review => const ReviewScreen(),
      SuggestionTarget.invoices => const InvoicesScreen(),
      SuggestionTarget.bank => const BankScreen(),
      SuggestionTarget.vat => const VatScreen(),
    };
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => screen),
    );
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  static String _today() {
    final d = DateTime.now();
    String two(int n) => n.toString().padLeft(2, '0');
    return '${d.year}-${two(d.month)}-${two(d.day)}';
  }

  Future<void> _load() async {
    final settings = await AppSettings.load();
    Account? account;
    try {
      account = await _auth.account();
    } catch (_) {
      // No account (or no MSAL on this platform): signed-out tiles.
      account = null;
    }
    if (!mounted) return;
    setState(() {
      _settings = settings;
      _account = account;
      _loading = account != null;
      _error = null;
      _refresh++;
    });
    if (account == null) return;
    try {
      // The VAT estimate uses the saved VAT period (Settings › VAT
      // quarter); dashboard() sends it as stagger=/start_month=.
      final client =
          await booksClient(settings, _auth, account);
      final json = await client.dashboard(today: _today());
      if (!mounted) return;
      setState(() => _data = Dashboard.fromJson(json));
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  List<Widget> _tiles() {
    if (_account == null) {
      return const [
        HomeTile(label: 'Cash in bank', value: '—', note: 'Connect to see'),
        HomeTile(label: 'Owed to you', value: '—', note: 'Connect to see'),
        HomeTile(label: 'VAT estimate', value: '—', note: 'Calculated by code'),
        HomeTile(label: 'Needs attention', value: '—', note: 'Connect to see'),
      ];
    }
    if (_loading) {
      return const [
        HomeTile(label: 'Cash in bank'),
        HomeTile(label: 'Owed to you'),
        HomeTile(label: 'VAT estimate'),
        HomeTile(label: 'Needs attention'),
      ];
    }
    final d = _data;
    if (d == null) {
      // The runtime could not be reached: the message is shown above.
      return const [
        HomeTile(label: 'Cash in bank', value: '—', note: 'Could not load'),
        HomeTile(label: 'Owed to you', value: '—', note: 'Could not load'),
        HomeTile(label: 'VAT estimate', value: '—', note: 'Could not load'),
        HomeTile(label: 'Needs attention', value: '—', note: 'Could not load'),
      ];
    }
    final overdue = d.overdueInvoices ?? 0;
    final owedBy = d.owedByYouPence;
    final attention = d.attentionTotal;
    final box5 = double.tryParse(d.vatBox5 ?? '');
    final vat = box5 == null
        ? '—'
        : d.vatDirection == 'nil'
            ? '£0'
            : poundsFromPence((box5 * 100).round());
    final vatVerb = d.vatDirection == 'reclaim'
        ? 'Reclaim'
        : d.vatDirection == 'nil'
            ? 'Nothing to pay'
            : 'Pay';
    return [
      HomeTile(
        label: 'Cash in bank',
        value: poundsFromPence(d.cashPence),
        note: d.cashAsOf == null
            ? 'Match a bank line to see'
            : 'Balance on ${shortDate(d.cashAsOf)}',
      ),
      HomeTile(
        label: 'Owed to you',
        value: poundsFromPence(d.owedToYouPence),
        note: overdue > 0
            ? '$overdue overdue'
            : owedBy == null
                ? 'Unpaid sales'
                : 'You owe ${poundsFromPence(owedBy)}',
        amber: overdue > 0,
      ),
      // Only for a VAT-registered business (the profile's features).
      if (d.vatApplies)
        HomeTile(
          label: 'VAT estimate',
          value: vat,
          note: d.vatDeadline == null
              ? 'Calculated by code'
              : '$vatVerb by ${shortDate(d.vatDeadline)}',
        ),
      HomeTile(
        label: 'Needs attention',
        value: attention?.toString() ?? '—',
        note: attention == null
            ? '—'
            : attention == 0
                ? 'Nothing waiting'
                : 'Review now',
        amber: (attention ?? 0) > 0,
      ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final signedIn = _account != null;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
              signedIn
                  ? 'Hello, ${AuthService.displayName(_account!).split(' ').first}'
                  : 'Your books. Your cloud. Meta AI on your terms.',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 6),
          Text(
            signedIn
                ? 'Worked out by code from the books in your own folder. '
                    'Pull down to refresh.'
                : 'Accnomos keeps your bookkeeping in a folder you own (OneDrive first), '
                    'reads receipts and invoices with Meta AI, and files VAT returns to HMRC '
                    'only when you say so.',
            style: const TextStyle(color: AccnomosColors.muted, height: 1.4),
          ),
          if (_error != null) ...[
            const SizedBox(height: 10),
            Text('Could not load your figures: $_error',
                style: const TextStyle(color: AccnomosColors.muted, fontSize: 12)),
          ],
          const SizedBox(height: 20),
          GridView.count(
            crossAxisCount: 2,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            mainAxisSpacing: 12,
            crossAxisSpacing: 12,
            childAspectRatio: 1.35,
            children: _tiles(),
          ),
          const SizedBox(height: 12),
          if (signedIn && _settings != null) ...[
            SampleBooksCard(
              clientFor: () => booksClient(_settings!, _auth, _account),
              onLoaded: _load,
            ),
            const SizedBox(height: 12),
          ],
          if (_data?.vatAssumed == true) const AssumedStaggerNote(),
          if (_data?.vatAssumed == true) const SizedBox(height: 12),
          TodosCard(
            settings: _settings ?? AppSettings(),
            auth: _auth,
            account: _account,
            suggestions: _data == null
                ? const []
                : suggestionsFor(_data!),
            onOpen: _openSuggestion,
            refresh: _refresh,
          ),
          const SizedBox(height: 12),
          if (_settings != null)
            InboxCard(
              settings: _settings!,
              auth: _auth,
              account: _account,
            ),
          if (!signedIn) ...[
            const SizedBox(height: 20),
            FilledButton(
              style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size.fromHeight(52),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14))),
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const SettingsScreen()),
              ),
              child: const Text('Connect your cloud',
                  style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
            ),
          ],
          const SizedBox(height: 10),
          const Text(
            'Accnomos never stores your data on its own servers.',
            textAlign: TextAlign.center,
            style: TextStyle(color: AccnomosColors.muted, fontSize: 12),
          ),
        ],
      ),
    );
  }
}

/// "Assuming Mar/Jun/Sep/Dec quarters — set yours in Settings", shown when
/// the runtime assumed calendar quarters (no stagger saved), worded like
/// the web's Deadlines note. The link opens Settings.
class AssumedStaggerNote extends StatelessWidget {
  const AssumedStaggerNote({super.key});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        const Text(
          'Assuming Mar/Jun/Sep/Dec quarters —',
          style: TextStyle(
              color: Color(0xFF8A3F06),
              fontSize: 13,
              fontWeight: FontWeight.w600,
              height: 1.4),
        ),
        TextButton(
          style: TextButton.styleFrom(
            padding: EdgeInsets.zero,
            minimumSize: Size.zero,
            tapTargetSize: MaterialTapTargetSize.shrinkWrap,
          ),
          onPressed: () => Navigator.of(context).push(
            MaterialPageRoute(builder: (_) => const SettingsScreen()),
          ),
          child: const Text(
            'set yours in Settings',
            style: TextStyle(
                color: Color(0xFF8A3F06),
                fontSize: 13,
                fontWeight: FontWeight.w800,
                decoration: TextDecoration.underline,
                height: 1.4),
          ),
        ),
      ],
    );
  }
}

/// One Home tile. A null [value] draws grey bars while the figures load.
class HomeTile extends StatelessWidget {
  const HomeTile(
      {super.key, required this.label, this.value, this.note, this.amber = false});
  final String label;
  final String? value;
  final String? note;
  final bool amber;

  static Widget _bar(double width, double height) => Container(
        width: width,
        height: height,
        decoration: BoxDecoration(
            color: AccnomosColors.ground,
            borderRadius: BorderRadius.circular(6)),
      );

  @override
  Widget build(BuildContext context) {
    final value = this.value;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label.toUpperCase(),
              style: const TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: AccnomosColors.muted,
                  letterSpacing: 0.6)),
          const Spacer(),
          if (value == null) ...[
            _bar(72, 26),
            const SizedBox(height: 6),
            _bar(96, 12),
          ] else ...[
            Text(value,
                style: const TextStyle(
                    fontSize: 26,
                    fontWeight: FontWeight.w800,
                    color: AccnomosColors.ink)),
            Text(note ?? '',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                    fontSize: 12,
                    fontWeight: amber ? FontWeight.w700 : FontWeight.w400,
                    color: amber ? const Color(0xFFB45309) : AccnomosColors.muted)),
          ],
        ],
      ),
    );
  }
}
