import 'package:accnomos_mobile/screens/ask_screen.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Speech-to-text provenance on Android: the "Transcribed by …" note and
/// when the mic is on (the user's key, or a server speech-to-text chain).
void main() {
  test('VoiceAnswer reads who transcribed it', () {
    final voice = VoiceAnswer.fromJson({
      'transcript': 'Andy did 2 hours overtime at double time on the Hendon job',
      'transcribed_by': {
        'provider': 'whisper',
        'label': 'Whisper on the DGX Spark',
        'model': 'Systran/faster-whisper-large-v3',
        'fallback_reason': 'Muse Voice Transcribe: Muse Voice returned HTTP 503',
      },
    });
    expect(voice.transcribedBy, 'Whisper on the DGX Spark');
    expect(VoiceAnswer.fromJson({'transcript': 'x'}).transcribedBy, isNull);
    expect(
      VoiceAnswer.fromJson({'transcript': 'x', 'transcribed_by': null})
          .transcribedBy,
      isNull,
    );
  });

  testWidgets('the spoken tag names the service that heard it',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(
        body: Column(children: [
          SpokenTag(heardBy: 'Muse Voice Transcribe'),
          SpokenTag(),
        ]),
      ),
    ));
    expect(find.text('Spoken · Transcribed by Muse Voice Transcribe'),
        findsOneWidget);
    expect(find.text('Spoken'), findsOneWidget);
  });

  test('voice is on with a key, or with the server speech-to-text', () {
    final ok = {'voice': true};
    expect(voiceOffReason('key', ok), isNull);
    expect(voiceOffReason('local', ok), contains('Meta API key'));
    expect(
      voiceOffReason('local', {
        'voice': true,
        'stt': [
          {'name': 'muse', 'configured': false},
          {'name': 'whisper', 'configured': true},
        ],
      }),
      isNull,
    );
    expect(voiceOffReason('key', {'voice': false}), contains('ffmpeg'));
    expect(voiceOffReason('local', null), contains('Meta API key'));
    expect(voiceOffReason('key', null), isNull);
  });
}
