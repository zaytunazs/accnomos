import 'model_names.dart';

/// The summary at the top of Home, from `GET /books/home`
/// (services/runtime/app/home_overview.py, app/ai/home_summary.py): code
/// works out every figure; the user's AI, if set up, only words them, and
/// code checks every number it wrote. The same text the web shows.
///
/// Newer servers also send `items`: the summary as a short list, already
/// sorted by code (most urgent first), each with an optional action that
/// opens the page where the task is done. Older servers send only
/// `summary_md`, which is shown as before.
class HomeSummary {
  const HomeSummary({
    required this.text,
    required this.model,
    this.fallbackReason,
    this.items = const [],
  });

  final String text;

  /// "code" when no AI is set up.
  final String model;

  /// Why code wrote it instead of the AI (no AI, or the AI's words failed
  /// the number check); null when the AI's words passed.
  final String? fallbackReason;

  /// The summary as a list, in the order the server sent it; empty when the
  /// server sends none (then [text] is shown).
  final List<SummaryItem> items;

  bool get byAi => model != 'code' && fallbackReason == null;

  /// The "who did what" line under the summary.
  String get byLine => byAi
      ? 'Every figure by code from your books · worded by your AI '
          '(${friendlyModelName(model)}), '
          'numbers checked by code'
      : 'Every figure by code from your books · '
          '${fallbackReason ?? 'written by code'}';

  /// From the whole `GET /books/home` JSON; null if it has no summary.
  static HomeSummary? fromHomeJson(Map<String, dynamic> json) {
    final s = json['summary'];
    if (s is! Map) return null;
    final raw = s['summary_md'];
    final text = raw is String ? raw.trim() : '';
    final items = <SummaryItem>[];
    final list = s['items'];
    if (list is List) {
      for (final e in list) {
        final item = SummaryItem.fromJson(e);
        if (item != null) items.add(item);
      }
    }
    if (text.isEmpty && items.isEmpty) return null;
    return HomeSummary(
      text: text,
      model: s['model'] is String ? s['model'] as String : 'code',
      fallbackReason: s['fallback_reason'] is String
          ? s['fallback_reason'] as String
          : null,
      items: items,
    );
  }
}

enum SummaryTone { negative, warning, positive, neutral }

/// One line of the summary: a title, an optional detail and an optional
/// action. `priority` 1 is the most urgent; 3 is background.
class SummaryItem {
  const SummaryItem({
    required this.id,
    required this.title,
    this.detail,
    this.priority = 2,
    this.tone = SummaryTone.neutral,
    this.action,
  });

  final String id;
  final String title;
  final String? detail;
  final int priority;
  final SummaryTone tone;
  final SummaryAction? action;

  /// Lenient: anything without a title is skipped (null).
  static SummaryItem? fromJson(Object? e) {
    if (e is! Map) return null;
    final title = e['title'];
    if (title is! String || title.trim().isEmpty) return null;
    final detail = e['detail'];
    final p = e['priority'];
    final priority = p is num ? p.toInt().clamp(1, 3) : 2;
    return SummaryItem(
      id: e['id'] is String ? e['id'] as String : title.trim(),
      title: title.trim(),
      detail: detail is String && detail.trim().isNotEmpty ? detail.trim() : null,
      priority: priority,
      tone: switch (e['tone']) {
        'negative' => SummaryTone.negative,
        'warning' => SummaryTone.warning,
        'positive' => SummaryTone.positive,
        _ => SummaryTone.neutral,
      },
      action: SummaryAction.fromJson(e['action']),
    );
  }
}

/// What a summary line's button does: a label ("Review") and the web path of
/// the page where the task is done ("/review"), which the app maps to its own
/// screen (lib/services/summary_routes.dart).
class SummaryAction {
  const SummaryAction({required this.label, required this.route});

  final String label;
  final String route;

  static SummaryAction? fromJson(Object? a) {
    if (a is! Map) return null;
    final label = a['label'];
    final route = a['route'];
    if (label is! String || label.trim().isEmpty) return null;
    if (route is! String || route.trim().isEmpty) return null;
    return SummaryAction(label: label.trim(), route: route.trim());
  }
}
