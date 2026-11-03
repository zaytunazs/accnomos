/// One hands-free turn on the phone: record WAV (16 kHz mono, as hold-to-talk)
/// until the speaker stops, using the recorder's amplitude for the level and
/// [decide] for the end of speech. Nothing leaves the phone here.
library;

import 'dart:async';
import 'dart:io';

import 'package:record/record.dart';

import 'hands_free.dart';

class MicRefused implements Exception {
  MicRefused(this.message);
  final String message;
  @override
  String toString() => message;
}

/// Record until silence. Returns the WAV bytes, or null when nothing was said
/// (or [stopped] became true). [onLevel] gets 0–1 for a level meter.
Future<List<int>?> recordUntilSilence(
  AudioRecorder mic, {
  required bool Function() stopped,
  void Function(double level)? onLevel,
}) async {
  bool allowed = false;
  try {
    allowed = await mic.hasPermission();
  } catch (_) {
    allowed = false;
  }
  if (!allowed) {
    throw MicRefused('Microphone access was refused. Allow it in the phone '
        'settings, or type your question instead.');
  }
  final path =
      '${Directory.systemTemp.path}/accnomos_handsfree_${DateTime.now().millisecondsSinceEpoch}.wav';
  await mic.start(
    const RecordConfig(
      encoder: AudioEncoder.wav,
      sampleRate: 16000,
      numChannels: 1,
    ),
    path: path,
  );
  final started = DateTime.now().millisecondsSinceEpoch;
  int? heard;
  var outcome = Tick.carryOn;
  while (outcome == Tick.carryOn) {
    await Future<void>.delayed(const Duration(milliseconds: 100));
    if (stopped()) {
      outcome = Tick.empty;
      break;
    }
    double db = -160;
    try {
      db = (await mic.getAmplitude()).current;
    } catch (_) {
      db = -160;
    }
    final now = DateTime.now().millisecondsSinceEpoch;
    onLevel?.call(((db + 60) / 60).clamp(0.0, 1.0));
    if (db >= speechDbfs) heard = now;
    outcome = decide(now, started, heard);
  }
  onLevel?.call(0);
  String? saved;
  try {
    saved = await mic.stop();
  } catch (_) {
    saved = null;
  }
  final file = File(saved ?? path);
  List<int> bytes = const [];
  try {
    if (outcome == Tick.end) bytes = await file.readAsBytes();
  } catch (_) {
    bytes = const [];
  }
  try {
    await file.delete();
  } catch (_) {
    // Best effort: the OS clears the temp folder anyway.
  }
  return outcome == Tick.end && bytes.isNotEmpty ? bytes : null;
}
