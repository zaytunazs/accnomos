import 'package:flutter/material.dart';

import '../services/ai_route.dart';
import '../theme.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);

/// "Which AI answers first" (Settings › AI only): three radio tiles, the
/// same options and words as the web's `AiRouteChoice`. The local-only
/// warning always sits under that option and is highlighted once it is
/// picked. [value] is the option shown as chosen ([kDefaultAiRoute] when
/// nothing is saved); [onChanged] saves.
class AiRoutePicker extends StatelessWidget {
  const AiRoutePicker({
    super.key,
    required this.value,
    required this.onChanged,
    this.enabled = true,
  });

  final String value;
  final ValueChanged<String> onChanged;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final localOnly = value == 'local_only';
    return Column(
      key: const Key('aiRoutePicker'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Semantics(
          header: true,
          child: const Text(kAiRouteTitle,
              style: TextStyle(
                  fontWeight: FontWeight.w700, color: AccnomosColors.ink)),
        ),
        const SizedBox(height: 4),
        const Text(kAiRouteIntro,
            style: TextStyle(
                color: AccnomosColors.muted, fontSize: 12, height: 1.4)),
        RadioGroup<String>(
          groupValue: value,
          onChanged: (v) {
            if (!enabled || v == null) return;
            onChanged(v);
          },
          child: IgnorePointer(
            ignoring: !enabled,
            child: Opacity(
              opacity: enabled ? 1.0 : 0.6,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final opt in kAiRouteOptions) ...[
                    RadioListTile<String>(
                      key: Key('aiRoute_${opt.value}'),
                      value: opt.value,
                      title: Row(
                        children: [
                          Expanded(
                            child: Text(opt.label,
                                style: const TextStyle(
                                    fontWeight: FontWeight.w700,
                                    color: AccnomosColors.ink)),
                          ),
                          if (opt.badge != null) _Badge(opt.badge!),
                        ],
                      ),
                      subtitle: Text(opt.description,
                          style: const TextStyle(
                              color: AccnomosColors.muted,
                              fontSize: 12,
                              height: 1.4)),
                      contentPadding: EdgeInsets.zero,
                      dense: true,
                    ),
                    if (opt.value == 'local_only')
                      _LocalOnlyWarning(selected: localOnly),
                  ],
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: AccnomosColors.tealTint,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(text,
          style: const TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w800,
              color: AccnomosColors.tealDark)),
    );
  }
}

class _LocalOnlyWarning extends StatelessWidget {
  const _LocalOnlyWarning({required this.selected});
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final ink = selected ? _warnInk : AccnomosColors.muted;
    return Container(
      key: Key(selected ? 'aiRouteWarningSelected' : 'aiRouteWarning'),
      width: double.infinity,
      margin: const EdgeInsets.only(left: 8, bottom: 4),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: selected ? _warnBg : AccnomosColors.ground,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: selected ? _warnBorder : AccnomosColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(kLocalOnlyWarningTitle,
              style: TextStyle(
                  color: ink, fontWeight: FontWeight.w800, height: 1.4)),
          const SizedBox(height: 4),
          for (final line in kLocalOnlyWarnings)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('• ',
                      style: TextStyle(color: ink, fontSize: 12, height: 1.4)),
                  Expanded(
                    child: Text(line,
                        style:
                            TextStyle(color: ink, fontSize: 12, height: 1.4)),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
