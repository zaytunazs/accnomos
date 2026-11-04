/// Which AI answers first (model routing): the Meta Model API (Muse Spark)
/// or the local model (Muse Glimmer 30B, on the user's own computer when one
/// is set up in Settings › AI, otherwise on Accnomos's own server).
///
/// Saved on this phone under [kAiRouteKey] and sent as [kAiRouteHeader] on
/// every runtime call once chosen; with nothing saved the header is left out
/// and the runtime keeps its default (Meta Model API first). Same options and
/// words as the web's `apps/web/src/lib/ai-route.ts`.
library;

const String kAiRouteKey = 'accnomos.ai.route';
const String kAiRouteHeader = 'X-AI-Route';
const String kDefaultAiRoute = 'meta_first';

const List<String> kAiRoutes = ['meta_first', 'local_first', 'local_only'];

/// The saved value when it is one of [kAiRoutes], else null.
String? clampAiRoute(String? value) =>
    value != null && kAiRoutes.contains(value) ? value : null;

typedef AiRouteOption = ({
  String value,
  String label,
  String? badge,
  String description,
});

const List<AiRouteOption> kAiRouteOptions = [
  (
    value: 'meta_first',
    label: 'Meta Model API first',
    badge: 'RECOMMENDED',
    description:
        'Best accuracy and voice. The local model takes over only if the Meta Model API is down.',
  ),
  (
    value: 'local_first',
    label: 'Local model first, Meta API when unsure',
    badge: null,
    description:
        "Saves Meta credits and keeps most of your data off the Meta Model API. When the local model's answer does not come back in a usable form, or the local model is down, the same request goes to the Meta Model API.",
  ),
  (
    value: 'local_only',
    label: 'Local model only',
    badge: null,
    description: 'Nothing is sent to the Meta Model API.',
  ),
];

const String kAiRouteTitle = 'Which AI answers first';

const String kAiRouteIntro =
    "Muse Spark runs on the Meta Model API. The local model, Muse Glimmer 30B, runs on your own computer if you set one up above, otherwise on Accnomos's own server.";

const String kLocalOnlyWarningTitle = 'What local only means';

const List<String> kLocalOnlyWarnings = [
  'Slower: reading a receipt or invoice can take a minute or more.',
  'Less accurate on messy photos, handwriting and long PDFs, so more items are left for you to check.',
  'No voice input: speech-to-text (Muse Voice Transcribe) runs on the Meta Model API. You can still type, and replies can still be read out by your device.',
  'If the local model is offline, AI features wait; nothing falls back.',
  'Every number is still checked by code before anything is saved, whichever you pick.',
];
