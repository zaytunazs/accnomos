import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/goals.dart';
import '../services/app_mode.dart';
import '../services/auth.dart';
import '../services/books.dart' show booksClient, isoDate;
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import 'goals_widgets.dart';
import 'settings_screen.dart';

/// Builds the runtime client for the Goals screen; tests inject a fake.
typedef GoalsClientFactory = RuntimeClient Function(AppSettings settings);

/// Goals & progress (`GET /books/goals`): targets for the business or the
/// household, tracked by code against the books. Signed in, goals can be
/// added, money put aside recorded, and goals removed; signed out it shows
/// clearly labelled fictional sample goals for the sample being viewed.
class GoalsScreen extends StatefulWidget {
  const GoalsScreen({
    super.key,
    this.clientFactory,
    @visibleForTesting this.testAccount,
    @visibleForTesting this.testAccountReady = false,
    @visibleForTesting this.today,
  });

  final GoalsClientFactory? clientFactory;

  @visibleForTesting
  final Account? testAccount;

  @visibleForTesting
  final bool testAccountReady;

  /// The date goals are measured to (tests only); null is today.
  @visibleForTesting
  final DateTime? today;

  @override
  State<GoalsScreen> createState() => _GoalsScreenState();
}

class _GoalsScreenState extends State<GoalsScreen> {
  final AuthService _auth = AuthService();
  AppSettings? _settings;
  Account? _account;
  bool _checked = false;
  bool _loading = false;
  String? _error;
  GoalsData? _data;

  DateTime get _today => widget.today ?? DateTime.now();

  @override
  void initState() {
    super.initState();
    AppMode.state.addListener(_modeChanged);
    _load();
  }

  @override
  void dispose() {
    AppMode.state.removeListener(_modeChanged);
    super.dispose();
  }

  void _modeChanged() {
    if (mounted && _account == null) setState(() {});
  }

  Future<void> _load() async {
    final settings = await AppSettings.load();
    Account? account;
    if (widget.testAccountReady) {
      account = widget.testAccount;
    } else {
      try {
        account = await _auth.account();
      } catch (_) {
        account = null;
      }
    }
    if (!mounted) return;
    setState(() {
      _settings = settings;
      _account = account;
      _checked = true;
    });
    if (account != null) await _reload();
  }

  Future<RuntimeClient> _client() async {
    final factory = widget.clientFactory;
    if (factory != null) return factory(_settings!);
    return booksClient(_settings!, _auth, _account);
  }

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final json = await (await _client()).goals(today: isoDate(_today));
      if (!mounted) return;
      setState(() => _data = GoalsData.fromJson(json));
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = goalError(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  bool get _signedIn => _account != null;

  GoalsData get _shown =>
      _signedIn ? (_data ?? const GoalsData(goals: [], note: GoalsNote(text: '', model: 'code')))
                : sampleGoals(household: AppMode.state.value.sample == 'household');

  bool get _household =>
      _signedIn ? (_data?.household ?? AppMode.household) : AppMode.household;

  Future<void> _add() async {
    final added = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => AddGoalSheet(
        household: _household,
        today: _today,
        save: (body) async => (await _client()).addGoal(body),
      ),
    );
    if (added == true) await _reload();
  }

  Future<void> _details(GoalView g) async {
    final changed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => GoalDetailsSheet(
        goal: g,
        sample: !_signedIn,
        recordSaved: (pence) async =>
            (await _client()).patchGoal(g.id, {'saved_pence': pence}),
        remove: () async => (await _client()).deleteGoal(g.id),
      ),
    );
    if (changed == true) await _reload();
  }

  @override
  Widget build(BuildContext context) {
    final data = _shown;
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text('Goals & progress',
            style: Theme.of(context).textTheme.headlineSmall),
        actions: [
          if (_signedIn)
            IconButton(
              icon: const Icon(Icons.refresh_outlined),
              tooltip: 'Reload goals',
              constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : _reload,
            ),
        ],
      ),
      body: !_checked
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _signedIn ? _reload : () async {},
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
                children: [
                  Text(
                    _household
                        ? 'Targets for your household — saving for something, spending less — tracked against your own bank lines. Nothing here changes your books.'
                        : 'Targets for the business, tracked against the evidence in your books. Nothing here changes them.',
                    style: const TextStyle(
                        color: AccnomosColors.muted, height: 1.4),
                  ),
                  const SizedBox(height: 12),
                  if (_signedIn)
                    FilledButton.icon(
                      style: FilledButton.styleFrom(
                        backgroundColor: AccnomosColors.teal,
                        minimumSize: const Size.fromHeight(48),
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(8)),
                      ),
                      onPressed: _add,
                      icon: const Icon(Icons.add),
                      label: const Text('Add a goal',
                          style: TextStyle(fontWeight: FontWeight.w700)),
                    )
                  else
                    _SampleNote(household: _household),
                  const SizedBox(height: 16),
                  if (_loading && _data == null)
                    const Padding(
                      padding: EdgeInsets.all(24),
                      child: Center(child: CircularProgressIndicator()),
                    ),
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Text('Could not load your goals: $_error',
                          style: const TextStyle(color: Color(0xFF8A3F06))),
                    ),
                  GoalsNotePanel(note: data.note),
                  if (_signedIn && _data != null && data.goals.isEmpty)
                    const _EmptyGoals(),
                  for (final g in data.goals)
                    GoalCard(goal: g, onDetails: () => _details(g)),
                ],
              ),
            ),
    );
  }
}

class _SampleNote extends StatelessWidget {
  const _SampleNote({required this.household});
  final bool household;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF4DC),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            household
                ? 'Sample — fictional household figures'
                : 'Sample — fictional company figures',
            style: const TextStyle(
                fontWeight: FontWeight.w700, color: Color(0xFF8A470D)),
          ),
          const SizedBox(height: 4),
          const Text('Sign in with Microsoft to set goals for your own books.',
              style: TextStyle(color: Color(0xFF8A470D))),
          const SizedBox(height: 8),
          OutlinedButton(
            style: OutlinedButton.styleFrom(
              minimumSize: const Size(48, 44),
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8)),
            ),
            onPressed: () => Navigator.of(context)
                .push(MaterialPageRoute(builder: (_) => const SettingsScreen()))
                .then((_) => AppMode.refresh()),
            child: const Text('Open settings to sign in'),
          ),
        ],
      ),
    );
  }
}

class _EmptyGoals extends StatelessWidget {
  const _EmptyGoals();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AccnomosColors.border),
      ),
      child: const Text(
        'No goals yet. Add one — for example "Save £1,000 for the school fee by September" or "Spend 10% less on groceries this year" — and the app tracks it against your books.',
        style: TextStyle(color: AccnomosColors.muted, height: 1.4),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Details: biggest movers, suggestions, money put aside, remove.
// ---------------------------------------------------------------------------

class GoalDetailsSheet extends StatefulWidget {
  const GoalDetailsSheet({
    super.key,
    required this.goal,
    required this.sample,
    required this.recordSaved,
    required this.remove,
  });

  final GoalView goal;
  final bool sample;
  final Future<void> Function(int savedPence) recordSaved;
  final Future<void> Function() remove;

  @override
  State<GoalDetailsSheet> createState() => _GoalDetailsSheetState();
}

class _GoalDetailsSheetState extends State<GoalDetailsSheet> {
  final _amount = TextEditingController();
  bool _busy = false;
  bool _confirmDelete = false;
  String? _error;

  @override
  void dispose() {
    _amount.dispose();
    super.dispose();
  }

  Future<void> _record() async {
    final pence = parsePounds(_amount.text);
    if (pence == null || pence <= 0) {
      setState(() => _error = 'Enter an amount in pounds, for example 50.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.recordSaved(widget.goal.savedPence + pence);
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) setState(() => _error = goalError(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _remove() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.remove();
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) setState(() => _error = goalError(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final g = widget.goal;
    return Padding(
      padding: EdgeInsets.only(
          bottom: MediaQuery.of(context).viewInsets.bottom),
      child: ListView(
        shrinkWrap: true,
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
        children: [
          Text(g.name,
              style: const TextStyle(
                  fontSize: 20, fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text('${g.kindLabel} · ${g.periodLabel}',
              style: const TextStyle(color: AccnomosColors.muted)),
          const SizedBox(height: 8),
          Text(g.varianceText,
              style: TextStyle(
                  fontWeight: FontWeight.w700,
                  color: ToneColors.of(g.tone).text)),
          if (g.baselineLabel != null) ...[
            const SizedBox(height: 8),
            Text('Compared with: ${g.baselineLabel}',
                style: const TextStyle(color: AccnomosColors.muted)),
          ],
          if (g.drivers.isNotEmpty) ...[
            const SizedBox(height: 16),
            const Text('Biggest movers',
                style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
            const SizedBox(height: 4),
            const Text('This span against the same number of days just before.',
                style: TextStyle(color: AccnomosColors.muted, fontSize: 12)),
            const SizedBox(height: 6),
            for (final d in g.drivers)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Row(
                  children: [
                    Expanded(child: Text(d.name)),
                    Text(money(d.thisPence),
                        style: const TextStyle(
                            fontFeatures: [FontFeature.tabularFigures()])),
                    const SizedBox(width: 10),
                    SizedBox(
                      width: 92,
                      child: Text(
                        d.changePence >= 0
                            ? '+${money(d.changePence)}'
                            : money(d.changePence),
                        textAlign: TextAlign.right,
                        style: TextStyle(
                            fontFeatures: const [FontFeature.tabularFigures()],
                            color: d.changePence > 0
                                ? const Color(0xFFA12626)
                                : AccnomosColors.muted),
                      ),
                    ),
                  ],
                ),
              ),
          ],
          if (g.suggestions.isNotEmpty) ...[
            const SizedBox(height: 16),
            const Text('Suggestions',
                style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
            const SizedBox(height: 6),
            for (final s in g.suggestions)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text('• $s', style: const TextStyle(height: 1.4)),
              ),
            const Text('Worked out by code from your books.',
                style: TextStyle(color: AccnomosColors.muted, fontSize: 12)),
          ],
          const SizedBox(height: 8),
          Text(g.sourceText,
              style: const TextStyle(color: AccnomosColors.muted, fontSize: 12)),
          if (widget.sample) ...[
            const SizedBox(height: 16),
            const Text('Sample — fictional figures. Sign in to keep your own goals.',
                style: TextStyle(color: Color(0xFF8A470D))),
          ] else ...[
            if (g.kind == 'save') ...[
              const SizedBox(height: 20),
              const Text('Record money put aside',
                  style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
              const SizedBox(height: 8),
              TextField(
                key: const Key('goal-put-aside'),
                controller: _amount,
                keyboardType:
                    const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                  labelText: 'Amount (£)',
                  helperText: 'Added to the ${money(g.savedPence)} recorded so far',
                  border: const OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 8),
              FilledButton(
                style: FilledButton.styleFrom(
                    backgroundColor: AccnomosColors.teal,
                    minimumSize: const Size.fromHeight(44)),
                onPressed: _busy ? null : _record,
                child: const Text('Record it'),
              ),
            ],
            const SizedBox(height: 20),
            if (!_confirmDelete)
              OutlinedButton(
                style: OutlinedButton.styleFrom(
                    minimumSize: const Size.fromHeight(44),
                    foregroundColor: const Color(0xFFA12626)),
                onPressed: _busy
                    ? null
                    : () => setState(() => _confirmDelete = true),
                child: const Text('Remove this goal'),
              )
            else ...[
              const Text('Remove this goal? Your books are not changed.',
                  style: TextStyle(fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: FilledButton(
                      style: FilledButton.styleFrom(
                          backgroundColor: const Color(0xFFA12626),
                          minimumSize: const Size.fromHeight(44)),
                      onPressed: _busy ? null : _remove,
                      child: const Text('Yes, remove it'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton(
                      style: OutlinedButton.styleFrom(
                          minimumSize: const Size.fromHeight(44)),
                      onPressed: _busy
                          ? null
                          : () => setState(() => _confirmDelete = false),
                      child: const Text('Keep it'),
                    ),
                  ),
                ],
              ),
            ],
          ],
          if (_error != null) ...[
            const SizedBox(height: 10),
            Text(_error!, style: const TextStyle(color: Color(0xFFA12626))),
          ],
        ],
      ),
    );
  }
}

/// "12.50" or "£1,200" → pence; null when it is not an amount.
int? parsePounds(String text) {
  final clean = text.replaceAll(RegExp(r'[£,\s]'), '');
  if (clean.isEmpty) return null;
  final value = double.tryParse(clean);
  if (value == null || value.isNaN || value.isInfinite) return null;
  return (value * 100).round();
}

// ---------------------------------------------------------------------------
// Add a goal: four plain-English templates.
// ---------------------------------------------------------------------------

enum GoalTemplate { save, spendLess, spendCap, earn }

class AddGoalSheet extends StatefulWidget {
  const AddGoalSheet({
    super.key,
    required this.household,
    required this.today,
    required this.save,
  });

  final bool household;
  final DateTime today;
  final Future<Map<String, dynamic>> Function(Map<String, dynamic> body) save;

  @override
  State<AddGoalSheet> createState() => _AddGoalSheetState();
}

class _AddGoalSheetState extends State<AddGoalSheet> {
  GoalTemplate _template = GoalTemplate.save;
  final _name = TextEditingController();
  final _amount = TextEditingController();
  final _percent = TextEditingController(text: '10');
  final _focus = TextEditingController();
  final _saved = TextEditingController();
  late DateTime _start;
  late DateTime _end;
  String _measure = 'manual';
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _defaults();
  }

  @override
  void dispose() {
    for (final c in [_name, _amount, _percent, _focus, _saved]) {
      c.dispose();
    }
    super.dispose();
  }

  void _defaults() {
    final t = DateTime(widget.today.year, widget.today.month, widget.today.day);
    switch (_template) {
      case GoalTemplate.save:
        _start = t;
        _end = DateTime(t.year + 1, t.month, t.day);
      case GoalTemplate.spendLess:
        _start = DateTime(t.year, 1, 1);
        _end = DateTime(t.year, 12, 31);
      case GoalTemplate.spendCap:
      case GoalTemplate.earn:
        _start = DateTime(t.year, t.month, 1);
        _end = DateTime(t.year, t.month + 1, 0);
    }
  }

  String _label(GoalTemplate t) => switch (t) {
        GoalTemplate.save => 'Save for something',
        GoalTemplate.spendLess => 'Spend less',
        GoalTemplate.spendCap => 'Keep spending under a limit',
        GoalTemplate.earn =>
          widget.household ? 'Reach an income figure' : 'Reach a sales figure',
      };

  String get _defaultName => switch (_template) {
        GoalTemplate.save => 'Savings goal',
        GoalTemplate.spendLess => _focus.text.trim().isEmpty
            ? 'Spend less'
            : 'Spend less on ${_focus.text.trim()}',
        GoalTemplate.spendCap => _focus.text.trim().isEmpty
            ? 'Spending limit'
            : '${_focus.text.trim()} under limit',
        GoalTemplate.earn => widget.household ? 'Income target' : 'Sales target',
      };

  Map<String, dynamic>? _body() {
    final name = _name.text.trim().isEmpty ? _defaultName : _name.text.trim();
    final body = <String, dynamic>{
      'name': name,
      'kind': switch (_template) {
        GoalTemplate.save => 'save',
        GoalTemplate.spendLess => 'spend_less',
        GoalTemplate.spendCap => 'spend_cap',
        GoalTemplate.earn => 'earn',
      },
      'start': isoDate(_start),
      'end': isoDate(_end),
    };
    if (_template == GoalTemplate.spendLess) {
      final p = int.tryParse(_percent.text.trim());
      if (p == null || p < 1 || p > 90) {
        _error = 'Give a percentage between 1 and 90.';
        return null;
      }
      body['percent'] = p;
    } else {
      final pence = parsePounds(_amount.text);
      if (pence == null || pence <= 0) {
        _error = 'Give the amount in pounds.';
        return null;
      }
      body['target_pence'] = pence;
    }
    if (_template == GoalTemplate.spendLess ||
        _template == GoalTemplate.spendCap) {
      final f = _focus.text.trim();
      if (f.isNotEmpty) body['focus'] = f;
    }
    if (_template == GoalTemplate.save) {
      body['measure'] = _measure;
      final saved = parsePounds(_saved.text);
      if (saved != null && saved > 0) body['saved_pence'] = saved;
    }
    return body;
  }

  Future<void> _submit() async {
    setState(() => _error = null);
    final body = _body();
    if (body == null) {
      setState(() {});
      return;
    }
    setState(() => _busy = true);
    try {
      await widget.save(body);
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) setState(() => _error = goalError(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _pick(bool start) async {
    final picked = await showDatePicker(
      context: context,
      initialDate: start ? _start : _end,
      firstDate: DateTime(widget.today.year - 3),
      lastDate: DateTime(widget.today.year + 4),
    );
    if (picked != null) setState(() => start ? _start = picked : _end = picked);
  }

  Widget _field(TextEditingController c, String label,
      {String? hint, bool number = false, Key? key}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextField(
        key: key,
        controller: c,
        keyboardType: number
            ? const TextInputType.numberWithOptions(decimal: true)
            : TextInputType.text,
        decoration: InputDecoration(
          labelText: label,
          hintText: hint,
          border: const OutlineInputBorder(),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final t = _template;
    return Padding(
      padding:
          EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: ListView(
        shrinkWrap: true,
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
        children: [
          const Text('Add a goal',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          const Text(
              'The app tracks it against your books; nothing here changes them.',
              style: TextStyle(color: AccnomosColors.muted)),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final option in GoalTemplate.values)
                ChoiceChip(
                  label: Text(_label(option)),
                  selected: option == t,
                  onSelected: (_) => setState(() {
                    _template = option;
                    _defaults();
                    _error = null;
                  }),
                ),
            ],
          ),
          const SizedBox(height: 16),
          _field(_name, 'Name',
              hint: switch (t) {
                GoalTemplate.save => 'School fee',
                GoalTemplate.spendLess => 'Spend less on coffee',
                GoalTemplate.spendCap => 'Groceries under £350',
                GoalTemplate.earn =>
                  widget.household ? 'Monthly income' : 'November sales',
              },
              key: const Key('goal-name')),
          if (t == GoalTemplate.spendLess || t == GoalTemplate.spendCap)
            _field(_focus, 'What on (optional)',
                hint: widget.household
                    ? 'A category such as Groceries, or a word such as coffee'
                    : 'A category such as Travel, or a word such as fuel',
                key: const Key('goal-focus')),
          if (t == GoalTemplate.spendLess)
            _field(_percent, 'Cut by (%)',
                number: true, key: const Key('goal-percent'))
          else
            _field(
                _amount,
                switch (t) {
                  GoalTemplate.save => 'Amount to save (£)',
                  GoalTemplate.spendCap => 'Spending limit (£)',
                  _ => widget.household ? 'Income to reach (£)' : 'Sales to reach (£)',
                },
                number: true,
                key: const Key('goal-amount')),
          if (t == GoalTemplate.save) ...[
            const Text('How to count progress',
                style: TextStyle(fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            SegmentedButton<String>(
              key: const Key('goal-measure'),
              segments: const [
                ButtonSegment(
                    value: 'manual', label: Text("I'll record it")),
                ButtonSegment(
                    value: 'net_cash', label: Text('Count my bank')),
              ],
              selected: {_measure},
              onSelectionChanged: (v) => setState(() => _measure = v.first),
            ),
            const SizedBox(height: 4),
            Text(
              _measure == 'manual'
                  ? 'Progress is what you record as put aside.'
                  : 'Progress is money in minus money out on your bank lines since the start, plus anything recorded by hand.',
              style: const TextStyle(color: AccnomosColors.muted, fontSize: 12),
            ),
            const SizedBox(height: 12),
            _field(_saved, 'Already put aside (£, optional)', number: true),
          ],
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(44)),
                  onPressed: () => _pick(true),
                  child: Text('From ${isoDate(_start)}'),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton(
                  style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(44)),
                  onPressed: () => _pick(false),
                  child: Text(
                      t == GoalTemplate.save ? 'By ${isoDate(_end)}' : 'To ${isoDate(_end)}'),
                ),
              ),
            ],
          ),
          if (_error != null) ...[
            const SizedBox(height: 10),
            Text(_error!,
                key: const Key('goal-error'),
                style: const TextStyle(color: Color(0xFFA12626))),
          ],
          const SizedBox(height: 16),
          FilledButton(
            key: const Key('goal-save'),
            style: FilledButton.styleFrom(
                backgroundColor: AccnomosColors.teal,
                minimumSize: const Size.fromHeight(48)),
            onPressed: _busy ? null : _submit,
            child: Text(_busy ? 'Saving…' : 'Save goal'),
          ),
        ],
      ),
    );
  }
}
