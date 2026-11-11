/// Which AI answers first (model routing): the hosted model's API
/// or the local open-weights model (on the user's own computer when one
/// is set up in Settings › AI, otherwise on Accnomos's own server).
///
/// Saved on this phone under [kAiRouteKey] and sent as [kAiRouteHeader] on
/// every runtime call once chosen; with nothing saved the header is left out
/// and the runtime keeps its default. Same options and
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
    label: 'Hosted model first',
    badge: 'RECOMMENDED',
    description:
        'Best accuracy and voice. The local model takes over only if the hosted model is down.',
  ),
  (
    value: 'local_first',
    label: 'Local model first, hosted model when unsure',
    badge: null,
    description:
        "Saves hosted-model credits and keeps most of your data off the hosted model. When the local model's answer does not come back in a usable form, or the local model is down, the same request goes to the hosted model.",
  ),
  (
    value: 'local_only',
    label: 'Local model only',
    badge: null,
    description: 'Nothing is sent to the hosted model.',
  ),
];

const String kAiRouteTitle = 'Which AI answers first';

const String kAiRouteIntro =
    "The hosted model runs on its provider's API. The local model, an open-weights model, runs on your own computer if you set one up above, otherwise on Accnomos's own server.";

const String kLocalOnlyWarningTitle = 'What local only means';

const List<String> kLocalOnlyWarnings = [
  'Slower: reading a receipt or invoice can take a minute or more.',
  'Less accurate on messy photos, handwriting and long PDFs, so more items are left for you to check.',
  "No voice input: speech-to-text runs on the hosted model's API. You can still type, and replies can still be read out by your device.",
  'If the local model is offline, AI features wait; nothing falls back.',
  'Every number is still checked by code before anything is saved, whichever you pick.',
];
