/// The summary at the top of Home, from `GET /books/home`
/// (services/runtime/app/home_overview.py, app/ai/home_summary.py): code
/// works out every figure; the user's AI, if set up, only words them, and
/// code checks every number it wrote. The same text the web shows.
class HomeSummary {
  const HomeSummary({
    required this.text,
    required this.model,
    this.fallbackReason,
  });

  final String text;

  /// "code" when no AI is set up.
  final String model;

  /// Why code wrote it instead of the AI (no AI, or the AI's words failed
  /// the number check); null when the AI's words passed.
  final String? fallbackReason;

  bool get byAi => model != 'code' && fallbackReason == null;

  /// The "who did what" line under the summary.
  String get byLine => byAi
      ? 'Every figure by code from your books · worded by your AI ($model), '
          'numbers checked by code'
      : 'Every figure by code from your books · '
          '${fallbackReason ?? 'written by code'}';

  /// From the whole `GET /books/home` JSON; null if it has no summary.
  static HomeSummary? fromHomeJson(Map<String, dynamic> json) {
    final s = json['summary'];
    if (s is! Map) return null;
    final text = s['summary_md'];
    if (text is! String || text.trim().isEmpty) return null;
    return HomeSummary(
      text: text.trim(),
      model: s['model'] is String ? s['model'] as String : 'code',
      fallbackReason: s['fallback_reason'] as String?,
    );
  }
}
