import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/dashboard.dart';
import '../models/home_summary.dart';
import '../models/suggestions.dart';
import '../services/auth.dart';
import '../services/books.dart' show booksClient;
import '../services/app_mode.dart';
import '../services/books_events.dart';
import '../services/runtime_client.dart' show RuntimeClient;
import '../services/settings.dart';
import '../services/summary_routes.dart';
import '../theme.dart';
import '../widgets/loading.dart';
import '../widgets/tile_grid.dart';
import 'bank_screen.dart';
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

/// The summary at the top of Home, figures by code. Newer servers send it as
/// a short list sorted by code (most urgent first), each line with a button
/// to the page where the task is done; older servers send a paragraph.
class SummaryCard extends StatelessWidget {
  const SummaryCard({
    super.key,
    required this.summary,
    this.pending = false,
    this.household,
  });

  final HomeSummary summary;

  /// Code's summary is showing and the AI's words are on their way: a thin
  /// teal bar along the top and "Muse Spark is writing your summary…".
  final bool pending;

  /// Which app the actions open pages in; null reads it from [AppMode].
  final bool? household;

  @override
  Widget build(BuildContext context) {
    final isHousehold = household ?? AppMode.household;
    // Background lines (priority 3) go last, the rest keep the server's order.
    final items = [
      ...summary.items.where((i) => i.priority < 3),
      ...summary.items.where((i) => i.priority >= 3),
    ];
    final body = items.isEmpty
        ? Text(summary.text,
            key: ValueKey(summary.text),
            style: const TextStyle(color: AccnomosColors.ink, height: 1.45))
        : Column(
            key: ValueKey(items.map((i) => '${i.id}:${i.title}').join('|')),
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // With items, summary_md is the one-line headline above them.
              if (summary.text.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text(summary.text,
                      key: const Key('summary-headline'),
                      style: const TextStyle(
                          color: AccnomosColors.ink, height: 1.4)),
                ),
              for (final (n, item) in items.indexed)
                SummaryItemRow(
                  item: item,
                  household: isHousehold,
                  divider: n > 0,
                ),
            ],
          );
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
                      child: body,
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

/// One summary line: a tone icon, the title in bold, the detail muted, and the
/// action ("Review →") when the app has a page for it. Text wraps at any font
/// size; nothing is cut off.
class SummaryItemRow extends StatelessWidget {
  const SummaryItemRow({
    super.key,
    required this.item,
    required this.household,
    this.divider = false,
  });

  final SummaryItem item;
  final bool household;
  final bool divider;

  static (IconData, Color, String) _tone(SummaryTone t) => switch (t) {
        SummaryTone.negative => (
            Icons.error_outline,
            const Color(0xFFA12626),
            'Needs attention'
          ),
        SummaryTone.warning => (
            Icons.schedule,
            const Color(0xFF8A470D),
            'Coming up'
          ),
        SummaryTone.positive => (
            Icons.check_circle_outline,
            const Color(0xFF166534),
            'Good news'
          ),
        SummaryTone.neutral => (
            Icons.info_outline,
            AccnomosColors.muted,
            'For information'
          ),
      };

  @override
  Widget build(BuildContext context) {
    final (icon, color, toneLabel) = _tone(item.tone);
    final background = item.priority >= 3;
    final action = item.action;
    final target =
        action == null ? null : summaryTarget(action.route, household: household);
    return Container(
      key: Key('summary-item-${item.id}'),
      padding: EdgeInsets.only(top: divider ? 10 : 2, bottom: 2),
      decoration: divider
          ? const BoxDecoration(
              border: Border(top: BorderSide(color: Color(0xFFC9E2DC))))
          : null,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 1, right: 10),
            child: Semantics(
              label: toneLabel,
              child: Icon(icon,
                  size: 20, color: background ? AccnomosColors.muted : color),
            ),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(item.title,
                    style: TextStyle(
                        fontWeight: background ? FontWeight.w600 : FontWeight.w700,
                        color: background ? AccnomosColors.muted : AccnomosColors.ink,
                        height: 1.3)),
                if (item.detail != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(item.detail!,
                        style: const TextStyle(
                            color: AccnomosColors.muted, fontSize: 13, height: 1.4)),
                  ),
                if (target != null)
                  TextButton(
                    key: Key('summary-action-${item.id}'),
                    style: TextButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 6),
                      minimumSize: const Size(48, 40),
                      alignment: Alignment.centerLeft,
                      foregroundColor: AccnomosColors.tealDark,
                    ),
                    onPressed: () => openSummaryTarget(context, target),
                    child: Text('${action!.label} →',
                        style: const TextStyle(fontWeight: FontWeight.w700)),
                  ),
              ],
            ),
          ),
        ],
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
