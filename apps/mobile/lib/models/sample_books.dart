/// `GET/POST /books/sample` (services/runtime/app/sample_books.py).
class SampleStatus {
  const SampleStatus({
    required this.state,
    this.step,
    this.done = 0,
    this.total = 0,
    this.steps = const [],
    this.error,
    this.business,
    this.empty,
  });

  /// `none`, `running`, `needs_token`, `done` or `failed`.
  final String state;

  /// The step being done, or the one it stopped at.
  final String? step;
  final int done;
  final int total;
  final List<String> steps;

  /// A plain sentence from the runtime when it stopped.
  final String? error;

  /// The fictional company.
  final String? business;

  /// State `none` only: whether sample books could go into this folder.
  final bool? empty;

  bool get running => state == 'running' || state == 'needs_token';

  factory SampleStatus.fromJson(Map<String, dynamic> json) {
    int whole(Object? v) => v is num ? v.toInt() : int.tryParse('$v') ?? 0;
    return SampleStatus(
      state: (json['state'] ?? 'none').toString(),
      step: json['step']?.toString(),
      done: whole(json['done']),
      total: whole(json['total']),
      steps: [
        if (json['steps'] is List)
          for (final s in json['steps'] as List) s.toString(),
      ],
      error: json['error']?.toString(),
      business: json['business']?.toString(),
      empty: json['empty'] is bool ? json['empty'] as bool : null,
    );
  }
}

/// The runtime answered 409/429/503 with a sentence (folder not empty, too
/// many requests, not available on this server). A note to show, not a
/// failure. [message] is the runtime's own sentence.
class SampleNote implements Exception {
  SampleNote(this.message);
  final String message;

  @override
  String toString() => message;
}
