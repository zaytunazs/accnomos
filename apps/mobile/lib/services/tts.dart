/// Reading answers aloud with the phone's own text-to-speech (Android's
/// TextToSpeech, British English where installed), through a small platform
/// channel in MainActivity.kt. No package, nothing sent anywhere.
library;

import 'package:flutter/services.dart';

class Speaker {
  Speaker({MethodChannel? channel})
      : _channel = channel ?? const MethodChannel('accnomos/tts');
  final MethodChannel _channel;

  /// Speak [text]; completes when it has been said, or at once when the
  /// phone has no voice (the answer is on screen either way).
  Future<void> say(String text) async {
    if (text.trim().isEmpty) return;
    try {
      await _channel.invokeMethod<void>('speak', {'text': text});
    } on PlatformException {
      // No TTS engine: silent, the words are on screen.
    } on MissingPluginException {
      // Tests and other platforms.
    }
  }

  Future<void> stop() async {
    try {
      await _channel.invokeMethod<void>('stop');
    } on PlatformException {
      // Nothing speaking.
    } on MissingPluginException {
      // Tests and other platforms.
    }
  }
}
