/// Verbal approval in the assistant — the same rules as the web's
/// `apps/web/src/lib/voiceApproval.ts`.
///
/// After a card is shown, the assistant reads it back in words and asks
/// "Shall I go ahead? Say yes or no." A clear yes sends the same signed
/// `POST /actions/approve` the Approve button sends, marked `via: "voice"`
/// with what was heard (the runtime checks the words again and audits them).
/// No, cancel or silence: nothing happens and the card stays for tapping.
/// Unclear: ask once more, then leave it. A card the runtime marks
/// `tap_only` (it sends or moves money: `app/actions.py` `needs_tap`) never
/// takes a spoken yes.
library;

import '../models/ask_answer.dart';
import '../models/readback.dart';
import 'hands_free.dart';

enum SpokenReply { yes, no, unclear }

/// Mirrors `app/actions.py` `YES_WORDS`: the whole reply must be a yes,
/// optionally with "please" or "thanks".
final _yes = RegExp(
  r"^\s*(?:yes|yeah|yep|yup|ok(?:ay)?|sure|approve(?:d)?|go ahead|do it|confirm(?:ed)?|please do|that'?s right)"
  r"\b[\s.!,]*(?:please|thanks|thank you)?[\s.!]*$",
  caseSensitive: false,
);
final _no = RegExp(
  r"^\s*(?:no|nope|nah|cancel|stop|don'?t|do not|leave it|not now|never mind|reject|wait)\b",
  caseSensitive: false,
);

/// How a spoken reply to "Shall I go ahead?" is taken. Silence is a no.
SpokenReply hearReply(String? text) {
  final t = (text ?? '').trim();
  if (t.isEmpty || _no.hasMatch(t)) return SpokenReply.no;
  return _yes.hasMatch(t) ? SpokenReply.yes : SpokenReply.unclear;
}

String _hour(int h, int m) {
  if (h == 12 && m == 0) return 'noon';
  final ap = h < 12 ? 'am' : 'pm';
  final h12 = h % 12 == 0 ? 12 : h % 12;
  return m == 0 ? '$h12 $ap' : '$h12 ${m.toString().padLeft(2, '0')} $ap';
}

/// Money and clock times as words for the phone's voice: "£40.00" → "forty
/// pounds", "15:00–16:00" → "3 pm to 4 pm".
String inWords(String text) => text
    .replaceAllMapped(RegExp(r'£\s?(\d[\d,]*)(?:\.(\d{2}))?'), (m) {
      final pounds = int.parse(m[1]!.replaceAll(',', ''));
      return penceInWords(pounds * 100 + int.parse(m[2] ?? '0'));
    })
    .replaceAllMapped(
        RegExp(r'\b([01]?\d|2[0-3]):([0-5]\d)\s*[–-]\s*([01]?\d|2[0-3]):([0-5]\d)\b'),
        (m) =>
            '${_hour(int.parse(m[1]!), int.parse(m[2]!))} to ${_hour(int.parse(m[3]!), int.parse(m[4]!))}')
    .replaceAllMapped(RegExp(r'\b([01]?\d|2[0-3]):([0-5]\d)\b'),
        (m) => _hour(int.parse(m[1]!), int.parse(m[2]!)));

/// What the assistant says after showing a card: the card in words, then the
/// question (or why it needs a tap).
String cardReadBack(ProposedAction a) {
  final said = inWords(speakable(a.summaryMd));
  final figures =
      readBack(a.kind, a.preview).map((f) => '${f.label}: ${f.words}.').join(' ');
  final body = trimForSpeech([said, figures].where((s) => s.isNotEmpty).join(' '));
  if (a.tapOnly) {
    return '$body This one sends or moves money, so it needs you to tap '
        "Approve on screen. I won't take a spoken yes for it.";
  }
  final clash = a.preview['conflicts'] is List && (a.preview['conflicts'] as List).isNotEmpty;
  return '$body ${clash ? 'Add it anyway?' : 'Shall I go ahead?'} Say yes or no.';
}

const askAgain = "Sorry, I didn't catch that. Say yes to go ahead, or no to leave it.";
const leftForTap =
    "Okay, I've left it on screen. Nothing has changed; you can tap Approve or Reject.";

/// The dialogue for one card. True when it was approved by a spoken yes.
///
/// [listen] records one reply (null when nothing was said); [transcribe]
/// turns it into words (`POST /books/ask/transcribe`); [approve] sends the
/// signed approval with what was heard and returns the result's summary, or
/// null when it failed (the card shows why).
Future<bool> approveByVoice({
  required ProposedAction action,
  required Future<void> Function(String text) speak,
  required Future<List<int>?> Function() listen,
  required Future<String?> Function(List<int> audio) transcribe,
  required Future<String?> Function(String heard) approve,
  void Function(HandsFreeState state)? onState,
  bool Function()? stopped,
}) async {
  bool off() => stopped?.call() ?? false;
  onState?.call(HandsFreeState.speaking);
  await speak(cardReadBack(action));
  if (off() || action.tapOnly) return false;
  for (var attempt = 0; attempt < 2; attempt++) {
    onState?.call(HandsFreeState.listening);
    final audio = await listen();
    if (off()) return false;
    var heard = '';
    if (audio != null && audio.isNotEmpty) {
      onState?.call(HandsFreeState.thinking);
      try {
        heard = (await transcribe(audio)) ?? '';
      } catch (_) {
        heard = ''; // not heard: taken as no; the card stays
      }
    }
    final reply = hearReply(heard);
    if (reply == SpokenReply.yes) {
      onState?.call(HandsFreeState.thinking);
      final result = await approve(heard);
      onState?.call(HandsFreeState.speaking);
      await speak(result != null
          ? trimForSpeech(inWords(speakable(result)))
          : "That didn't go through. The reason is on screen.");
      return result != null;
    }
    onState?.call(HandsFreeState.speaking);
    if (reply == SpokenReply.no) {
      await speak(leftForTap);
      return false;
    }
    if (attempt == 0) await speak(askAgain);
  }
  await speak(leftForTap);
  return false;
}
