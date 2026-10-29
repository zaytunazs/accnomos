import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// The Android app shows nothing that is not there yet: no "coming soon", "beta", "early access", "launching",
/// "testers" or "soon" in any text it can display. The same words are swept from every web page, signed in, signed
/// out and in the demo sandbox (apps/web/e2e/submission-mode.spec.ts).
///
/// Reads every string literal in lib/ (comments are left out: they are not shown) and the Android resource strings.
final _words = <RegExp>[
  RegExp(r'coming soon', caseSensitive: false),
  RegExp(r'\bbeta\b', caseSensitive: false),
  RegExp(r'early[ -]?access', caseSensitive: false),
  RegExp(r'\blaunch(ing|es)?\b', caseSensitive: false),
  RegExp(r'\btesters\b', caseSensitive: false),
  RegExp(r'\bsoon\b', caseSensitive: false),
  RegExp(r'coming next', caseSensitive: false),
  RegExp(r'not yet available', caseSensitive: false),
];

/// String literals on one line: '…' or "…" (escaped quotes allowed), not inside a // comment.
final _literal = RegExp(r'''('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")''');

Iterable<String> _literals(String line) {
  final code = line.trimLeft();
  if (code.startsWith('//')) return const [];
  // Drop a trailing // comment that is not inside a string (good enough for this code base's style).
  final cut = RegExp(r'''\s//\s(?=(?:[^'"]|'[^']*'|"[^"]*")*$)''').firstMatch(line);
  final body = cut == null ? line : line.substring(0, cut.start);
  return _literal.allMatches(body).map((m) => m.group(0)!);
}

void main() {
  test('no not-yet wording in any string the app can show', () {
    final hits = <String>[];
    final files = Directory('lib').listSync(recursive: true).whereType<File>().where((f) => f.path.endsWith('.dart'));
    for (final f in files) {
      final lines = f.readAsLinesSync();
      for (var i = 0; i < lines.length; i++) {
        for (final s in _literals(lines[i])) {
          for (final w in _words) {
            if (w.hasMatch(s)) hits.add('${f.path}:${i + 1}: $s');
          }
        }
      }
    }
    final res = Directory('android/app/src/main/res');
    if (res.existsSync()) {
      for (final f in res.listSync(recursive: true).whereType<File>().where((f) => f.path.endsWith('strings.xml'))) {
        final text = f.readAsStringSync();
        for (final w in _words) {
          if (w.hasMatch(text)) hits.add('${f.path}: ${w.pattern}');
        }
      }
    }
    expect(hits, isEmpty, reason: hits.join('\n'));
  });

  test('the sweep catches the words it is meant to', () {
    expect(_literals("  Text('iPhone app coming soon'),").any((s) => _words.any((w) => w.hasMatch(s))), isTrue);
    expect(_literals('  // available soon, in a comment').isEmpty, isTrue);
    expect(_literals("  Text('Due soonest first'),").any((s) => _words.any((w) => w.hasMatch(s))), isFalse);
  });
}
