import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/dashboard.dart';
import '../models/home_summary.dart';
import '../models/suggestions.dart';
import '../services/auth.dart';
import '../services/books.dart' show booksClient;
import '../services/books_events.dart';
import '../services/runtime_client.dart' show RuntimeClient;
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/calendar_sync.dart';
import '../widgets/loading.dart';
import '../widgets/tile_grid.dart';
import 'bank_screen.dart';
import 'calendar_screen.dart';
import 'home_cards.dart';
import 'invoices_screen.dart';
import 'month_end_screen.dart' show MonthEndCard;
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
  HomeSummary? _summary;

  /// Code's summary is on screen and the AI's words are still coming.
  bool _summaryPending = false;
  int _summaryGen = 0;
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

  int _seenChange = BooksEvents.changed.value;

  /// Home › Deadlines and the automatic calendar refresh (signed in only).
  DeadlineSync? _deadlines;

  @override
  void initState() {
    super.initState();
    BooksEvents.changed.addListener(_onBooksChanged);
    _load();
  }

  @override
  void dispose() {
    BooksEvents.changed.removeListener(_onBooksChanged);
    _deadlines?.dispose();
    super.dispose();
  }

  /// An approval or other change elsewhere: refresh the tiles (not the
  /// worded summary, which would cost a model call on every tap).
  Future<void> _onBooksChanged() async {
    if (BooksEvents.changed.value == _seenChange) return;
    _seenChange = BooksEvents.changed.value;
    final settings = _settings;
    final account = _account;
    if (!mounted || settings == null || account == null || _loading) return;
    try {
      final client = await booksClient(settings, _auth, account);
      final json = await client.dashboard(today: _today());
      if (mounted) {
        setState(() {
          _data = Dashboard.fromJson(json);
          _refresh++;
        });
      }
    } catch (_) {
      // The tiles keep their last figures; pull to refresh shows the error.
    }
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
    _deadlines?.dispose();
    _deadlines = account == null
        ? null
        : DeadlineSync(
            read: () => booksClient(settings, _auth, account),
            write: () => calendarClient(settings, _auth, account));
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
      // The summary loads beside the tiles and never holds them up.
      _loadSummary(client);
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

  /// Code's summary first (no model call, so it is quick), then the AI's
  /// words in the background, swapped in when they arrive. If the AI's
  /// words do not come, code's summary stays. An older load never overwrites
  /// a newer one.
  Future<void> _loadSummary(RuntimeClient client) async {
    final gen = ++_summaryGen;
    bool current() => mounted && gen == _summaryGen;
    if (!current()) return;
    setState(() => _summaryPending = true);
    try {
      final fast = await client.home(today: _today(), summaryAi: false);
      if (current()) {
        setState(() => _summary = HomeSummary.fromHomeJson(fast) ?? _summary);
      }
    } catch (_) {
      // The AI call below may still answer.
    }
    try {
      final full = await client.home(today: _today());
      final worded = HomeSummary.fromHomeJson(full);
      if (current() && worded != null) setState(() => _summary = worded);
    } catch (_) {
      // Code's summary stands.
    } finally {
      if (current()) setState(() => _summaryPending = false);
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
    if (_loading && _data == null) {
      // Same size as the real tiles, shimmering, so nothing jumps when the
      // figures arrive. A reload keeps the last figures on screen instead.
      return const [
        SkeletonTile(label: 'Cash in bank'),
        SkeletonTile(label: 'Owed to you'),
        SkeletonTile(label: 'VAT estimate'),
        SkeletonTile(label: 'Needs attention'),
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
                  ? 'Hello, ${AuthService.greetingName(_account!)}'
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
          if (signedIn && _summary != null) ...[
            const SizedBox(height: 14),
            SummaryCard(summary: _summary!, pending: _summaryPending),
          ] else if (signedIn && _summaryPending) ...[
            const SizedBox(height: 14),
            const SummaryCardSkeleton(),
          ],
          if (_error != null) ...[
            const SizedBox(height: 10),
            Text('Could not load your figures: $_error',
                style: const TextStyle(color: AccnomosColors.muted, fontSize: 12)),
          ],
          const SizedBox(height: 20),
          TileGrid(children: _tiles()),
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
          if (signedIn && _deadlines != null) ...[
            HomeDeadlinesCard(
              key: ValueKey(_deadlines),
              sync: _deadlines!,
              onOpenCalendar: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const CalendarScreen()),
              ),
            ),
            const SizedBox(height: 12),
          ],
          if (_settings != null)
            InboxCard(
              settings: _settings!,
              auth: _auth,
              account: _account,
            ),
          if (signedIn && _settings != null) ...[
            const SizedBox(height: 12),
            MonthEndCard(
              clientFor: () => booksClient(_settings!, _auth, _account),
              refresh: _refresh,
            ),
          ],
          if (!signedIn) ...[
            const SizedBox(height: 20),
            FilledButton(
              style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size.fromHeight(52),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12))),
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
/// The summary at the top of Home: two to four sentences, figures by code.
class SummaryCard extends StatelessWidget {
  const SummaryCard({super.key, required this.summary, this.pending = false});

  final HomeSummary summary;

  /// Code's summary is showing and the AI's words are on their way: a thin
  /// teal bar along the top and "Muse Spark is writing your summary…".
  final bool pending;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      label: 'Your summary',
      child: ClipRRect(
        borderRadius: BorderRadius.circular(16),
        child: Container(
          decoration: const BoxDecoration(color: AccnomosColors.tealTint),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(
                height: 3,
                child: pending
                    ? const LinearProgressIndicator(
                        key: Key('summary-progress'),
                        minHeight: 3,
                        color: AccnomosColors.teal,
                        backgroundColor: Color(0xFFC9E2DC),
                      )
                    : null,
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 11, 14, 14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Your summary',
                        style: TextStyle(
                            fontWeight: FontWeight.w800,
                            color: AccnomosColors.tealDark,
                            fontSize: 16)),
                    const SizedBox(height: 6),
                    AnimatedSwitcher(
                      duration: const Duration(milliseconds: 350),
                      child: Text(summary.text,
                          key: ValueKey(summary.text),
                          style: const TextStyle(
                              color: AccnomosColors.ink, height: 1.45)),
                    ),
                    const SizedBox(height: 8),
                    pending
                        ? const AiWritingBar(
                            key: Key('summary-writing'),
                            label: 'Muse Spark is writing your summary…')
                        : Text(summary.byLine,
                            style: const TextStyle(
                                color: AccnomosColors.muted, fontSize: 12)),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The summary card before even code's figures are in: its title and
/// shimmering lines, in the same teal card.
class SummaryCardSkeleton extends StatelessWidget {
  const SummaryCardSkeleton({super.key});

  @override
  Widget build(BuildContext context) => const SkeletonCard(
      key: Key('summary-skeleton'), title: 'Your summary', lines: 3, tinted: true);
}

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
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AccnomosColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Labels wrap as far as they need (large text sizes included).
          Text(label,
              style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AccnomosColors.muted)),
          const SizedBox(height: 10),
          const Spacer(),
          if (value == null) ...[
            _bar(72, 26),
            const SizedBox(height: 6),
            _bar(96, 12),
          ] else ...[
            Text(value,
                maxLines: 1,
                softWrap: false,
                overflow: TextOverflow.fade,
                style: const TextStyle(
                    fontSize: 26,
                    fontWeight: FontWeight.w800,
                    color: AccnomosColors.ink)),
            Text(note ?? '',
                maxLines: 3,
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
