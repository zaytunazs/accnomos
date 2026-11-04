/// A model id as people read it, with the names the web shows
/// (apps/web/src/lib/ai-config.ts `shortModelName`): "muse-spark-1.3-contributor"
/// -> "Muse Spark", "muse-glimmer:30b" -> "Glimmer 30B". A provider prefix the
/// runtime records ("meta:", the local server's or a host's) is dropped, so no
/// raw id or non-Meta name reaches the screen. "code" stays "code".
String friendlyModelName(String model) {
  final m = model
      .trim()
      .replaceFirst(
          RegExp(r'^(meta|ollama|baseten|modal|spark|local|key|test):'), '')
      .replaceFirst(RegExp(r'^meta-models/'), '');
  final lower = m.toLowerCase();
  if (lower == 'code') return 'code';
  if (lower == 'muse-glimmer:30b') return 'Glimmer 30B';
  if (lower.startsWith('muse-glimmer')) return 'Muse Glimmer';
  if (lower.startsWith('muse-spark-open')) return 'Muse Spark Open';
  if (lower.startsWith('muse-spark')) return 'Muse Spark';
  return m.isEmpty ? 'a model' : m;
}
