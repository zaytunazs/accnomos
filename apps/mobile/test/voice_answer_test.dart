import 'package:flutter_test/flutter_test.dart';

import 'package:accnomos_mobile/services/runtime_client.dart';

Map<String, dynamic> answerJson() => {
      'answer_md': 'Your Q3 bill is £2,140.',
      'key_numbers': [],
      'citations': [],
      'suggested_actions': [],
      'confidence': 'high',
      'model': 'muse-glimmer:30b',
      'period': {'start': '2026-07-01', 'end': '2026-09-30'},
      'fallback_reason': null,
    };

void main() {
  group('VoiceAnswer.fromJson', () {
    test('reads a nested answer with its transcript', () {
      final voice = VoiceAnswer.fromJson({
        'transcript': 'Why is my VAT higher?',
        'answer': answerJson(),
      });
      expect(voice.transcript, 'Why is my VAT higher?');
      expect(voice.answer, isNotNull);
      expect(voice.answer!.answerMd, 'Your Q3 bill is £2,140.');
    });

    test('reads a top-level ask-shaped answer', () {
      final voice = VoiceAnswer.fromJson({
        'transcript': 'Who did I spend most with?',
        ...answerJson(),
      });
      expect(voice.answer, isNotNull);
      expect(voice.answer!.confidence, 'high');
    });

    test('keeps the transcript when there is no answer', () {
      final voice = VoiceAnswer.fromJson({
        'transcript': 'Chase Howdens for the invoice',
      });
      expect(voice.transcript, 'Chase Howdens for the invoice');
      expect(voice.answer, isNull);
    });

    test('falls back to text and question keys', () {
      expect(
        VoiceAnswer.fromJson({'text': 'hello'}).transcript,
        'hello',
      );
      expect(
        VoiceAnswer.fromJson({'question': 'hello again'}).transcript,
        'hello again',
      );
      expect(VoiceAnswer.fromJson({}).transcript, '');
    });
  });
}
