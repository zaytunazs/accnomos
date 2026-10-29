/// A background scan (`services/runtime/app/scan_jobs.py`), as the web's
/// `RtScanJob` in `apps/web/src/lib/runtime.ts`: each file goes uploaded →
/// reading → confirm the type → checking → ready / needs a look / not read.
library;

/// The document types the reader asks the user to confirm, in the web's
/// order (`KIND_LABEL` in `apps/web/src/lib/scan-jobs.ts`).
const scanKindLabels = <String, String>{
  'receipt': 'Receipt',
  'purchase_invoice': 'Bill (purchase invoice)',
  'sales_invoice': 'Sales invoice',
  'bank_statement': 'Bank statement',
  'credit_note': 'Credit note',
  'payslip': 'Payslip',
  'other': 'Something else',
};

const _finalStages = {'ready', 'needs_a_look', 'failed'};

/// The AI's (or code's) guess of what a file is.
class ScanGuess {
  const ScanGuess({
    required this.kind,
    required this.confidence,
    required this.reason,
    required this.byCode,
  });

  final String kind;
  final double confidence;
  final String reason;

  /// True when code guessed (the AI did not answer in time, or a CSV).
  final bool byCode;

  String get label => scanKindLabels[kind] ?? kind;
  int get percent => (confidence * 100).round();

  static ScanGuess? fromJson(Object? raw) {
    if (raw is! Map) return null;
    final kind = (raw['kind'] ?? 'other').toString();
    final c = raw['confidence'];
    return ScanGuess(
      kind: scanKindLabels.containsKey(kind) ? kind : 'other',
      confidence: c is num ? c.toDouble().clamp(0, 1).toDouble() : 0,
      reason: (raw['reason'] ?? '').toString(),
      byCode: raw['by'] == 'code',
    );
  }
}

class ScanFile {
  const ScanFile({
    required this.name,
    required this.stage,
    required this.stageLabel,
    required this.progress,
    this.guess,
    this.kind,
    this.route,
    this.proposalId,
    this.message,
  });

  final String name;
  final String stage;
  final String stageLabel;
  final double progress;
  final ScanGuess? guess;
  final String? kind;
  final String? route;
  final String? proposalId;
  final String? message;

  bool get waitingForType => stage == 'confirm';
  bool get done => _finalStages.contains(stage);

  factory ScanFile.fromJson(Map<String, dynamic> json) {
    final p = json['progress'];
    String? text(String key) {
      final v = json[key];
      return v == null || v.toString().isEmpty ? null : v.toString();
    }

    return ScanFile(
      name: (json['name'] ?? '').toString(),
      stage: (json['stage'] ?? 'uploaded').toString(),
      stageLabel: (json['stage_label'] ?? json['stage'] ?? '').toString(),
      progress: p is num ? p.toDouble().clamp(0, 1).toDouble() : 0,
      guess: ScanGuess.fromJson(json['guess']),
      kind: text('kind'),
      route: text('route'),
      proposalId: text('proposal_id'),
      message: text('message'),
    );
  }
}

class ScanJob {
  const ScanJob({
    required this.id,
    required this.source,
    required this.status,
    required this.progress,
    required this.files,
    this.interrupted = false,
  });

  final String id;
  final String source;

  /// working | waiting (only the user's confirmation is missing) | done.
  final String status;
  final double progress;
  final List<ScanFile> files;
  final bool interrupted;

  bool get working => status == 'working';
  bool get done => status == 'done';
  List<ScanFile> get toConfirm =>
      [for (final f in files) if (f.waitingForType) f];

  /// Files that reached Review or Needs a look (a card to load).
  int get cards => files.where((f) => f.proposalId != null).length;

  factory ScanJob.fromJson(Map<String, dynamic> json) {
    final p = json['progress'];
    return ScanJob(
      id: (json['id'] ?? '').toString(),
      source: (json['source'] ?? 'upload').toString(),
      status: (json['status'] ?? 'working').toString(),
      progress: p is num ? p.toDouble().clamp(0, 1).toDouble() : 0,
      interrupted: json['interrupted'] == true,
      files: [
        if (json['files'] is List)
          for (final f in json['files'] as List)
            if (f is Map) ScanFile.fromJson(Map<String, dynamic>.from(f)),
      ],
    );
  }

  /// The headline the web shows (`headline()` in ScanProgress.tsx).
  String get headline {
    final n = files.length;
    final what = '$n file${n == 1 ? '' : 's'}';
    if (working) return 'Reading $what…';
    if (status == 'waiting') {
      return '${toConfirm.length} to confirm: what kind of document is it?';
    }
    final ready = files.where((f) => f.stage == 'ready').length;
    final look = files.where((f) => f.stage == 'needs_a_look').length;
    final failed = files.where((f) => f.stage == 'failed').length;
    final parts = [
      if (ready > 0) '$ready ready to review',
      if (look > 0) '$look need${look == 1 ? 's' : ''} a look',
      if (failed > 0) '$failed not read',
    ];
    return 'Done · ${parts.isEmpty ? what : parts.join(' · ')}';
  }
}
