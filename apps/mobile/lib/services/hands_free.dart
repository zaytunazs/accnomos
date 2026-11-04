/// Hands-free conversation: listen → answer → speak → listen again. The same
/// rules as the web's `apps/web/src/lib/handsfree.ts`.
///
/// One turn records until the speaker stops ([decide]), sends the recording
/// to `POST /books/ask/voice` (Muse Voice Transcribe hears it; the Ask
/// pipeline answers with every figure checked), reads the answer aloud, and
/// listens again. The loop ends on Stop, a stop phrase ("stop", "that's
/// all"…) or two quiet turns in a row. A card is read back and the user is
/// asked "Shall I go ahead?" (services/voice_approval.dart): a clear yes
/// approves it as the button does and the loop goes on; anything else, or a
/// card that sends or moves money, leaves it on screen and pauses the loop.
library;

import 'dart:async';

import '../models/ask_answer.dart';

enum HandsFreeState { off, listening, thinking, speaking }

const handsFreeLabels = {
  HandsFreeState.off: 'Hands-free is off',
  HandsFreeState.listening: 'Listening…',
  HandsFreeState.thinking: 'Thinking…',
  HandsFreeState.speaking: 'Speaking…',
};

/// Microphone level (dBFS, from the recorder's amplitude) above which the
/// sound counts as speech.
const speechDbfs = -38.0;
const silenceMs = 1200;
const maxTurnMs = 30000;
const noSpeechMs = 8000;
const maxEmptyTurns = 2;

enum Tick { carryOn, end, empty }

/// Quiet for [silenceMs] after speech ends the question; no speech for
/// [noSpeechMs] is an empty turn; [maxTurnMs] ends it whatever.
Tick decide(int nowMs, int startedMs, int? heardMs) {
  if (nowMs - startedMs >= maxTurnMs) {
    return heardMs == null ? Tick.empty : Tick.end;
  }
  if (heardMs == null) {
    return nowMs - startedMs >= noSpeechMs ? Tick.empty : Tick.carryOn;
  }
  return nowMs - heardMs >= silenceMs ? Tick.end : Tick.carryOn;
}

final _stop = RegExp(
  r"^\s*(?:ok(?:ay)?[,\s]+)?(?:stop(?: listening)?|that'?s all|that is all|"
  r"thanks?,? that'?s all|no more|goodbye|bye|cancel|end(?: the)? conversation|"
  r'nothing else)[.!\s]*$',
  caseSensitive: false,
);

/// "Stop", "that's all", "goodbye"… as the whole utterance (not "stop
/// paying Acme").
bool isStopPhrase(String text) => _stop.hasMatch(text.trim());

/// Markdown answer → plain sentences for speech.
String speakable(String md) => md
    .replaceAll(RegExp(r'```[\s\S]*?```'), ' ')
    .replaceAllMapped(RegExp(r'\[([^\]]+)\]\([^)]*\)'), (m) => m[1]!)
    .replaceAll(RegExp(r'[*_`#>|]+'), '')
    .replaceAll(RegExp(r'^\s*[-•]\s+', multiLine: true), '')
    .replaceAll(RegExp(r'\s*\n+\s*'), '. ')
    .replaceAll(RegExp(r'\.(\s*\.)+'), '.')
    .replaceAll(RegExp(r'\s{2,}'), ' ')
    .trim();

const speakMax = 600;

String trimForSpeech(String text) {
  if (text.length <= speakMax) return text;
  final cut = text.lastIndexOf('. ', speakMax);
  return '${text.substring(0, cut > 200 ? cut + 1 : speakMax)} The rest is on screen.';
}

/// What one spoken turn came back with.
class HandsFreeReply {
  HandsFreeReply({
    required this.transcript,
    required this.answerMd,
    this.needsApproval = false,
    this.action,
  });
  final String transcript;
  final String answerMd;

  /// A question with choices on screen (or a card with no voice approval
  /// wired): shown, and the loop pauses.
  final bool needsApproval;

  /// A card to approve: read back, then "Shall I go ahead?".
  final ProposedAction? action;
}

/// The loop itself, with the microphone, the Ask call and the voice injected
/// so it can be tested without a phone.
class HandsFreeLoop {
  HandsFreeLoop({
    required this.listen,
    required this.ask,
    required this.speak,
    required this.onState,
    this.onNote,
    this.approve,
  });

  /// Record one turn; null when nothing was said or the loop was stopped.
  final Future<List<int>?> Function(bool Function() stopped) listen;

  /// Send a recording; null when the call failed (the error is shown by the
  /// caller).
  final Future<HandsFreeReply?> Function(List<int> audio) ask;
  final Future<void> Function(String text) speak;
  final void Function(HandsFreeState state) onState;
  final void Function(String note)? onNote;

  /// The verbal approval dialogue for a card (voice_approval.dart
  /// `approveByVoice`); true when a spoken yes approved it.
  final Future<bool> Function(ProposedAction action)? approve;

  bool _stopped = false;
  bool get stopped => _stopped;
  bool _running = false;
  bool get running => _running;

  void stop() => _stopped = true;

  Future<void> run() async {
    if (_running) return;
    _running = true;
    _stopped = false;
    var empty = 0;
    try {
      while (!_stopped) {
        onState(HandsFreeState.listening);
        final audio = await listen(() => _stopped);
        if (_stopped) break;
        if (audio == null || audio.isEmpty) {
          empty += 1;
          if (empty >= maxEmptyTurns) {
            onNote?.call(
                "Hands-free stopped: I didn't hear anything. Tap Hands-free to start again.");
            break;
          }
          continue;
        }
        empty = 0;
        onState(HandsFreeState.thinking);
        final reply = await ask(audio);
        if (_stopped || reply == null) break;
        if (isStopPhrase(reply.transcript)) {
          onState(HandsFreeState.speaking);
          await speak('Okay.');
          break;
        }
        onState(HandsFreeState.speaking);
        final card = reply.action;
        if (card != null && approve != null) {
          final done = await approve!(card);
          if (_stopped) break;
          if (done) continue;
          onNote?.call('Hands-free paused: the card is on screen to tap.');
          break;
        }
        if (reply.needsApproval || card != null) {
          await speak(
              "I've put that on screen for you. Nothing changes until you choose.");
          onNote?.call('Hands-free paused: check the card on screen.');
          break;
        }
        await speak(trimForSpeech(speakable(reply.answerMd)));
      }
    } finally {
      _running = false;
      onState(HandsFreeState.off);
    }
  }
}
