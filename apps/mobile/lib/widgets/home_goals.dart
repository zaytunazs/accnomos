import 'package:flutter/material.dart';

import '../models/goals.dart';
import '../screens/goals_screen.dart';
import '../screens/goals_widgets.dart';
import '../services/runtime_client.dart';
import '../theme.dart';
import 'loading.dart';

/// Home › Goals & progress, as on the web (components/home/HomeGoals.tsx):
/// up to three goals, most urgent first, then the checked note. Code's note
/// comes first (no model call, so it is quick); the AI's note is swapped in
/// when it arrives, with "The AI is writing…" while it is on its way.
/// Its own GET /books/goals, so a failure here blanks only this card.
class HomeGoalsCard extends StatefulWidget {
  const HomeGoalsCard({
    super.key,
    required this.client,
    required this.today,
    this.refresh = 0,
  });

  final RuntimeClient client;
  final String today;

  /// Bumped by Home's pull-to-refresh: load again.
  final int refresh;

  @override
  State<HomeGoalsCard> createState() => _HomeGoalsCardState();
}

class _HomeGoalsCardState extends State<HomeGoalsCard> {
  GoalsData? _data;
  bool _writing = false;
  String? _error;
  int _gen = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(HomeGoalsCard old) {
    super.didUpdateWidget(old);
    if (old.refresh != widget.refresh || old.client != widget.client) _load();
  }

  Future<void> _load() async {
    final gen = ++_gen;
    bool current() => mounted && gen == _gen;
    try {
      final fast = GoalsData.fromJson(
          await widget.client.goals(today: widget.today, noteAi: false));
      if (!current()) return;
      setState(() {
        _data = fast;
        _error = null;
        _writing = fast.goals.isNotEmpty;
      });
      if (fast.goals.isEmpty) return;
      try {
        final full = GoalsData.fromJson(
            await widget.client.goals(today: widget.today));
        if (current()) setState(() => _data = full);
      } catch (_) {
        // Code's note stands.
      } finally {
        if (current()) setState(() => _writing = false);
      }
    } catch (e) {
      if (current()) setState(() => _error = goalError(e));
    }
  }

  void _open() => Navigator.of(context)
      .push(MaterialPageRoute<void>(builder: (_) => const GoalsScreen()))
      .then((_) => _load());

  @override
  Widget build(BuildContext context) {
    final data = _data;
    if (data == null && _error == null) return const SizedBox.shrink();
    final goals = data?.mostUrgentFirst.take(3).toList() ?? const <GoalView>[];
    return Semantics(
      container: true,
      label: 'Goals and progress',
      child: Container(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AccnomosColors.border),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('Goals & progress',
                style: TextStyle(
                    fontWeight: FontWeight.w800,
                    color: AccnomosColors.ink,
                    fontSize: 16)),
            const SizedBox(height: 2),
            const Text('Your targets, against the evidence in your books.',
                style: TextStyle(color: AccnomosColors.muted, fontSize: 13)),
            const SizedBox(height: 10),
            if (_error != null)
              Text('Could not load your goals: $_error',
                  style: const TextStyle(color: AccnomosColors.muted))
            else if (goals.isEmpty)
              const Text(
                  'No goals yet. Set one (save, spend less, earn more) and the AI '
                  'checks your progress against the books.',
                  style: TextStyle(color: AccnomosColors.ink, height: 1.4))
            else ...[
              for (final g in goals) ...[
                Row(
                  children: [
                    Expanded(
                      child: Text(g.name,
                          style: const TextStyle(fontWeight: FontWeight.w700)),
                    ),
                    StatusBadge(label: g.statusLabel, tone: g.tone),
                  ],
                ),
                const SizedBox(height: 4),
                GoalBar(goal: g),
                Text(g.varianceText,
                    style: const TextStyle(
                        color: AccnomosColors.muted, fontSize: 12)),
                const SizedBox(height: 10),
              ],
              if (data!.note.text.isNotEmpty)
                Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: AccnomosColors.tealTint,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      AnimatedSwitcher(
                        duration: const Duration(milliseconds: 300),
                        child: Text(data.note.text,
                            key: ValueKey(data.note.text),
                            style: const TextStyle(
                                color: AccnomosColors.ink, height: 1.4)),
                      ),
                      const SizedBox(height: 6),
                      _writing
                          ? const AiWritingBar(
                              key: Key('goals-writing'),
                              label: 'The AI is writing your goals note…')
                          : Text(data.note.byLine,
                              style: const TextStyle(
                                  color: AccnomosColors.muted, fontSize: 12)),
                    ],
                  ),
                ),
            ],
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton(
                key: const Key('home-goals-open'),
                onPressed: _open,
                child: Text(goals.isEmpty ? 'Set a goal' : 'All goals'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
