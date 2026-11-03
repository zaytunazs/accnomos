import 'package:accnomos_mobile/main.dart' show showAssistantButton;
import 'package:accnomos_mobile/services/hands_free.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('end of speech', () {
    test('quiet after speech ends the turn; no speech is an empty turn', () {
      expect(decide(500, 0, null), Tick.carryOn);
      expect(decide(noSpeechMs, 0, null), Tick.empty);
      expect(decide(3000, 0, 2500), Tick.carryOn);
      expect(decide(2500 + silenceMs, 0, 2500), Tick.end);
      expect(decide(maxTurnMs, 0, maxTurnMs - 10), Tick.end);
    });
  });

  test('stop phrases are the whole utterance only', () {
    for (final s in ['Stop', "that's all.", 'Okay, stop', 'goodbye', 'Thanks, that\'s all']) {
      expect(isStopPhrase(s), isTrue, reason: s);
    }
    for (final s in ['stop paying Acme', 'Who owes me the most?', 'is that all I owe?']) {
      expect(isStopPhrase(s), isFalse, reason: s);
    }
  });

  test('markdown is read as plain sentences', () {
    expect(speakable('**Sterling** owes you £7,479.60.\n- Hartwell £5,177.58'),
        'Sterling owes you £7,479.60. Hartwell £5,177.58');
    expect(trimForSpeech('a. ' * 400).endsWith('The rest is on screen.'), isTrue);
  });

  test('the assistant button is on every tab but Review and a business Ask tab', () {
    expect(showAssistantButton(household: false, tab: 0), isTrue);
    expect(showAssistantButton(household: false, tab: 1), isFalse);
    expect(showAssistantButton(household: false, tab: 2), isFalse);
    expect(showAssistantButton(household: true, tab: 2), isTrue); // Budget
    expect(showAssistantButton(household: true, tab: 1), isFalse);
  });

  group('the loop', () {
    late List<HandsFreeState> states;
    late List<String> spoken;
    late List<String> notes;

    HandsFreeLoop loop(List<List<int>?> turns, List<HandsFreeReply?> replies) {
      var t = 0;
      var r = 0;
      return HandsFreeLoop(
        listen: (_) async => t < turns.length ? turns[t++] : null,
        ask: (_) async => r < replies.length ? replies[r++] : null,
        speak: (s) async => spoken.add(s),
        onState: states.add,
        onNote: notes.add,
      );
    }

    setUp(() {
      states = [];
      spoken = [];
      notes = [];
    });

    test('listening → thinking → speaking → listening, then two quiet turns end it', () async {
      await loop(
        [
          [1, 2, 3],
          null,
          null,
        ],
        [HandsFreeReply(transcript: 'Who owes me the most?', answerMd: '**Sterling** owes £7,479.60.')],
      ).run();
      expect(states, [
        HandsFreeState.listening,
        HandsFreeState.thinking,
        HandsFreeState.speaking,
        HandsFreeState.listening,
        HandsFreeState.listening,
        HandsFreeState.off,
      ]);
      expect(spoken, ['Sterling owes £7,479.60.']);
      expect(notes.single, contains("didn't hear anything"));
    });

    test('"that\'s all" ends it without an answer being read', () async {
      await loop([
        [1]
      ], [
        HandsFreeReply(transcript: "That's all", answerMd: 'ignored'),
      ]).run();
      expect(spoken, ['Okay.']);
      expect(states.last, HandsFreeState.off);
    });

    test('a card to approve pauses hands-free; nothing is approved', () async {
      await loop([
        [1]
      ], [
        HandsFreeReply(transcript: 'Record £40 parking', answerMd: 'Card', needsApproval: true),
      ]).run();
      expect(spoken.single, contains('Nothing changes until you approve it'));
      expect(notes.single, contains('check the card'));
    });

    test('Stop ends it at once', () async {
      late HandsFreeLoop l;
      l = HandsFreeLoop(
        listen: (stopped) async {
          l.stop();
          return [1];
        },
        ask: (_) async => fail('must not ask after Stop'),
        speak: (_) async {},
        onState: states.add,
      );
      await l.run();
      expect(states, [HandsFreeState.listening, HandsFreeState.off]);
      expect(l.running, isFalse);
    });

    test('a failed ask ends the loop', () async {
      await loop([
        [1]
      ], [null]).run();
      expect(states, [HandsFreeState.listening, HandsFreeState.thinking, HandsFreeState.off]);
    });
  });
}
