/// Suggested questions for an empty Ask thread, built from the dashboard
/// payload in code — never by a model. Each question mirrors a tile on Home,
/// so the answer is one the books can actually give. Same wording as
/// `suggestedQuestions` in `apps/web/src/components/ask/suggested.ts`; the
/// input is the raw `GET /books/dashboard` JSON.
const List<String> askFallbackQuestions = [
  'Why is my VAT different from last quarter?',
  'Who owes me the most?',
  'What needs my attention?',
];

/// Up to four starters from the dashboard payload.
List<String> suggestedAskQuestions(Map<String, dynamic>? dashboard) {
  if (dashboard == null) return askFallbackQuestions;
  final out = <String>[];
  final vat = dashboard['vat'] is Map
      ? Map<String, dynamic>.from(dashboard['vat'] as Map)
      : null;
  if (vat != null) {
    final current = vat['current'] is Map
        ? Map<String, dynamic>.from(vat['current'] as Map)
        : null;
    final due = vat['due'] is Map
        ? Map<String, dynamic>.from(vat['due'] as Map)
        : null;
    if (current != null) {
      final currentBox5 = double.tryParse('${current['box5']}');
      final dueBox5 =
          due != null ? double.tryParse('${due['box5']}') : null;
      if (dueBox5 != null && currentBox5 != null && dueBox5 != currentBox5) {
        out.add(
          'Why is Box 5 ${dueBox5 > currentBox5 ? 'higher' : 'lower'} this quarter?',
        );
      } else {
        out.add(
          'Why is my VAT ${_gbp2('${current['box5']}')} for ${current['label']}?',
        );
      }
    }
  }
  int docs(Object? v) {
    if (v is Map) {
      final d = (v['documents'] ?? v['count']);
      if (d is num) return (d).toInt();
    }
    return 0;
  }

  final owedToYou = dashboard['owed_to_you'];
  final owedByYou = dashboard['owed_by_you'];
  if (docs(owedToYou) > 0) out.add('Who owes me the most?');
  if (docs(owedByYou) > 0) out.add('What do I owe and when is it due?');
  final attention = dashboard['attention'] is Map
      ? Map<String, dynamic>.from(dashboard['attention'] as Map)
      : null;
  int countAt(Object? v) => v is num ? v.toInt() : 0;
  if (countAt(attention?['unmatched_bank_lines']) > 0) {
    out.add('Which bank lines still need matching?');
  }
  if (countAt(attention?['proposed']) + countAt(attention?['needs_a_look']) >
      0) {
    out.add('What is waiting in Review?');
  }
  final cash = dashboard['cash'] is Map
      ? Map<String, dynamic>.from(dashboard['cash'] as Map)
      : null;
  if (cash != null && cash['balance_pence'] != null) {
    out.add('What is my cash balance?');
  }
  final picked = out.take(4).toList();
  return picked.isNotEmpty ? picked : askFallbackQuestions;
}

String _gbp2(String pounds) {
  final n = double.tryParse(pounds) ?? 0;
  final fixed = n.toStringAsFixed(2);
  final parts = fixed.split('.');
  final grouped = parts[0].replaceAllMapped(
    RegExp(r'(\d)(?=(\d{3})+$)'),
    (m) => '${m[1]},',
  );
  return '£$grouped.${parts.length > 1 ? parts[1] : '00'}';
}
