import 'package:flutter/material.dart';

import '../theme.dart';

/// Entries the Autopilot approved, as one compact line above the Review queue ("6 approved by Autopilot · Review or
/// undo"). The list with each Undo opens from it, so the document being reviewed keeps the screen.
class AutopilotSummary extends StatelessWidget {
  const AutopilotSummary({super.key, required this.count, required this.onOpen});

  final int count;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
      child: Material(
        color: AccnomosColors.tealTint,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          key: const Key('autopilot-summary'),
          borderRadius: BorderRadius.circular(10),
          onTap: onOpen,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 44),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Row(
                children: [
                  const Icon(Icons.auto_awesome_outlined, size: 18, color: AccnomosColors.tealDark),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      '$count approved by Autopilot · Review or undo',
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                          fontWeight: FontWeight.w600, fontSize: 14, color: AccnomosColors.tealDark),
                    ),
                  ),
                  const Icon(Icons.expand_more, color: AccnomosColors.tealDark),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
