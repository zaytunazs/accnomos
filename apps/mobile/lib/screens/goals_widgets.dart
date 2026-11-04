import 'package:flutter/material.dart';

import '../models/goals.dart';
import '../theme.dart';
import '../widgets/loading.dart';

/// Shared pieces of the goal cards (Goals screen and the household Home),
/// styled like the web's components/goals: a status badge by tone, a large
/// figure, an 8 px progress bar with the plan marker, the variance line in
/// the tone's colour, and the source line.

class ToneColors {
  const ToneColors(this.text, this.tint);
  final Color text;
  final Color tint;

  static ToneColors of(String tone) => switch (tone) {
        'positive' => const ToneColors(Color(0xFF166534), Color(0xFFECFDF3)),
        'warning' => const ToneColors(Color(0xFF8A470D), Color(0xFFFFF4DC)),
        'negative' => const ToneColors(Color(0xFFA12626), Color(0xFFFFF0F0)),
        _ => const ToneColors(Color(0xFF5C534B), Color(0xFFEEF2F4)),
      };
}

class StatusBadge extends StatelessWidget {
  const StatusBadge({super.key, required this.label, required this.tone});
  final String label;
  final String tone;

  @override
  Widget build(BuildContext context) {
    final c = ToneColors.of(tone);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
          color: c.tint, borderRadius: BorderRadius.circular(6)),
      child: Text(label,
          style: TextStyle(
              color: c.text, fontSize: 12, fontWeight: FontWeight.w700)),
    );
  }
}

/// The 8 px progress track: teal fill (red when the tone is negative), and
/// a thin marker where an even pace would be today, only when the runtime
/// gave a plan-to-date figure.
class GoalBar extends StatelessWidget {
  const GoalBar({super.key, required this.goal});
  final GoalView goal;

  @override
  Widget build(BuildContext context) {
    final target = goal.targetPence;
    final fill = target == null || target <= 0
        ? 0.0
        : (goal.currentPence / target).clamp(0.0, 1.0);
    final plan = goal.planToDatePence;
    final marker = target == null || target <= 0 || plan == null
        ? null
        : (plan / target).clamp(0.0, 1.0);
    final colour =
        goal.tone == 'negative' ? const Color(0xFFA12626) : AccnomosColors.teal;
    return SizedBox(
      height: 14,
      child: LayoutBuilder(builder: (context, box) {
        return Stack(
          alignment: Alignment.centerLeft,
          children: [
            Container(
              height: 8,
              decoration: BoxDecoration(
                  color: const Color(0xFFE6ECEF),
                  borderRadius: BorderRadius.circular(4)),
            ),
            Container(
              height: 8,
              width: box.maxWidth * fill,
              decoration: BoxDecoration(
                  color: colour, borderRadius: BorderRadius.circular(4)),
            ),
            if (marker != null)
              Positioned(
                left: (box.maxWidth * marker - 1).clamp(0.0, box.maxWidth - 2),
                child: Container(
                    width: 2, height: 14, color: AccnomosColors.ink),
              ),
          ],
        );
      }),
    );
  }
}

/// One goal card. [compact] (Home) leaves out the inset and source line.
class GoalCard extends StatelessWidget {
  const GoalCard(
      {super.key, required this.goal, this.onDetails, this.compact = false});

  final GoalView goal;
  final VoidCallback? onDetails;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final g = goal;
    final tone = ToneColors.of(g.tone);
    final percentLabel = g.percent == null
        ? null
        : g.spending
            ? '${g.percent}% of limit used'
            : '${g.percent}% of target';
    final run = g.runRatePence;
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: EdgeInsets.all(compact ? 14 : 16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AccnomosColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(g.name,
                    style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: AccnomosColors.ink)),
              ),
              const SizedBox(width: 8),
              StatusBadge(label: g.statusLabel, tone: g.tone),
            ],
          ),
          const SizedBox(height: 2),
          Text('${g.kindLabel} · ${g.periodLabel}',
              style: const TextStyle(
                  fontSize: 13, color: AccnomosColors.muted)),
          const SizedBox(height: 10),
          Text(moneyShort(g.currentPence),
              style: TextStyle(
                  fontSize: compact ? 24 : 28,
                  fontWeight: FontWeight.w700,
                  color: AccnomosColors.ink,
                  fontFeatures: const [FontFeature.tabularFigures()])),
          Text(g.targetLabel,
              style: const TextStyle(
                  fontSize: 13, color: AccnomosColors.muted)),
          if (g.targetPence != null) ...[
            const SizedBox(height: 10),
            GoalBar(goal: g),
            const SizedBox(height: 4),
            Wrap(
              alignment: WrapAlignment.spaceBetween,
              spacing: 12,
              children: [
                if (percentLabel != null)
                  Text(percentLabel,
                      style: const TextStyle(
                          fontSize: 13, color: AccnomosColors.muted)),
                if (g.planToDatePence != null)
                  Text('Plan to date: ${money(g.planToDatePence!)}',
                      style: const TextStyle(
                          fontSize: 13, color: AccnomosColors.muted)),
              ],
            ),
          ],
          const SizedBox(height: 8),
          Text(g.varianceText,
              style: TextStyle(
                  fontSize: 14, fontWeight: FontWeight.w700, color: tone.text)),
          if (!compact && (g.neededText != null || (run != null && run > 0))) ...[
            const SizedBox(height: 10),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AccnomosColors.ground,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (g.neededText != null)
                    Text(g.neededText!,
                        style: const TextStyle(
                            fontSize: 14, color: AccnomosColors.ink)),
                  if (run != null && run > 0) ...[
                    if (g.neededText != null) const SizedBox(height: 4),
                    Text(
                        'Run-rate estimate: ${money(run)} — at the same daily pace. Not guaranteed.',
                        style: const TextStyle(
                            fontSize: 13, color: AccnomosColors.ink)),
                  ],
                ],
              ),
            ),
          ],
          if (!compact) ...[
            const SizedBox(height: 8),
            Text(g.sourceText,
                style: const TextStyle(
                    fontSize: 12, color: AccnomosColors.muted)),
          ],
          if (onDetails != null)
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton(
                style: TextButton.styleFrom(
                  padding: EdgeInsets.zero,
                  minimumSize: const Size(48, 44),
                  foregroundColor: AccnomosColors.tealDark,
                ),
                onPressed: onDetails,
                child: const Text('View details →',
                    style: TextStyle(fontWeight: FontWeight.w700)),
              ),
            ),
        ],
      ),
    );
  }
}

/// "What your goals are telling you": a calm, pale-teal note.
class GoalsNotePanel extends StatelessWidget {
  const GoalsNotePanel({super.key, required this.note, this.pending = false});
  final GoalsNote note;

  /// The AI's note is still being written: code's note (if any) shows with
  /// "Muse Spark is reading your goals…" and a small spinner.
  final bool pending;

  @override
  Widget build(BuildContext context) {
    final hasText = note.text.trim().isNotEmpty;
    if (!hasText && !pending) return const SizedBox.shrink();
    return Semantics(
      container: true,
      label: 'What your goals are telling you',
      child: Container(
        width: double.infinity,
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AccnomosColors.tealTint,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFFC9E2DC)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Padding(
              padding: EdgeInsets.only(top: 2, right: 10),
              child: Icon(Icons.auto_awesome_outlined,
                  size: 20, color: AccnomosColors.tealDark),
            ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('What your goals are telling you',
                      style: TextStyle(
                          fontWeight: FontWeight.w700,
                          fontSize: 15,
                          color: AccnomosColors.ink)),
                  const SizedBox(height: 6),
                  if (hasText)
                    AnimatedSwitcher(
                      duration: const Duration(milliseconds: 350),
                      child: Text(note.text,
                          key: ValueKey(note.text),
                          style: const TextStyle(
                              color: AccnomosColors.ink, height: 1.45)),
                    )
                  else
                    const Shimmer(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          SkeletonBox(width: 240),
                          SizedBox(height: 8),
                          SkeletonBox(width: 180),
                        ],
                      ),
                    ),
                  const SizedBox(height: 8),
                  if (pending)
                    const AiWritingBar(
                        key: Key('note-writing'),
                        label: 'Muse Spark is reading your goals…')
                  else
                    Text(note.byLine,
                        style: const TextStyle(
                            color: AccnomosColors.muted, fontSize: 12)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
