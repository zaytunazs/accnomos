/// A model id as people read it, with the neutral names the web shows
/// (apps/web/src/lib/ai-config.ts `shortModelName`): "muse-spark-1.3-contributor"
/// -> "the hosted model", "muse-glimmer:30b" -> "the local open-weights model".
/// A provider prefix the runtime records (the hosted API's, the local server's
/// or a host's) is dropped, so no vendor or product name reaches the screen.
/// "code" stays "code".
String friendlyModelName(String model) {
  final m = model
      .trim()
      .replaceFirst(
          RegExp(r'^(meta|ollama|baseten|modal|spark|local|key|test|anthropic):'), '')
      .replaceFirst(RegExp(r'^meta-models/'), '');
  final lower = m.toLowerCase();
  if (lower == 'code') return 'code';
  if (lower.startsWith('muse-glimmer') || lower.startsWith('glimmer')) {
    return 'the local open-weights model';
  }
  if (lower.startsWith('muse-spark-open')) return 'the open-weights verifier model';
  if (lower.startsWith('muse-spark')) return 'the hosted model';
  if (lower.startsWith('claude')) return 'the backup model';
  return m.isEmpty ? 'a model' : m;
}
