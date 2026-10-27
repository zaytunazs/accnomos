/// Checked answer from `POST /books/ask` (see
/// `services/runtime/app/routes_ask.py`): numbers come from code, words from
/// the user's model, and every figure has been checked against the ledger.
class AskAnswer {
  AskAnswer({
    required this.answerMd,
    required this.keyNumbers,
    required this.citations,
    required this.suggestedActions,
    required this.confidence,
    required this.model,
    required this.periodStart,
    required this.periodEnd,
    this.fallbackReason,
    this.proposedAction,
    this.clarification,
  });

  /// Plain markdown (paragraphs, `-` and `1.` lists, `**bold**`).
  final String answerMd;
  final List<KeyNumber> keyNumbers;

  /// Paths in the user's books folder the answer used.
  final List<String> citations;
  final List<SuggestedAction> suggestedActions;

  /// `high`, `medium` or `low`.
  final String confidence;
  final String model;
  final String periodStart;
  final String periodEnd;

  /// Set when the model's words were replaced by the facts, quoted by code.
  final String? fallbackReason;

  /// An instruction ("log 7.5 hours for Sam on Elm Road") becomes a proposal
  /// that does nothing until approved. Kept exactly as received: it is signed,
  /// and `POST /actions/approve` refuses it if anything in it changes.
  final ProposedAction? proposedAction;

  /// An instruction Ask needs one more detail for (e.g. which customer).
  /// Renders as a question with the candidates as quick-reply chips.
  final Clarification? clarification;

  factory AskAnswer.fromJson(Map<String, dynamic> json) {
    List<Map<String, dynamic>> maps(Object? list) => [
          if (list is List)
            for (final item in list)
              if (item is Map) Map<String, dynamic>.from(item),
        ];
    final period = json['period'] is Map
        ? Map<String, dynamic>.from(json['period'] as Map)
        : const <String, dynamic>{};
    return AskAnswer(
      answerMd: (json['answer_md'] ?? '').toString(),
      keyNumbers: maps(json['key_numbers']).map(KeyNumber.fromJson).toList(),
      citations: [
        if (json['citations'] is List)
          for (final c in json['citations'] as List) c.toString(),
      ],
      suggestedActions:
          maps(json['suggested_actions']).map(SuggestedAction.fromJson).toList(),
      confidence: (json['confidence'] ?? 'low').toString(),
      model: (json['model'] ?? '').toString(),
      periodStart: (period['start'] ?? '').toString(),
      periodEnd: (period['end'] ?? '').toString(),
      fallbackReason: json['fallback_reason']?.toString(),
      proposedAction: json['proposed_action'] is Map
          ? ProposedAction(
              Map<String, dynamic>.from(json['proposed_action'] as Map))
          : null,
      clarification: json['clarification'] is Map
          ? Clarification.fromJson(
              Map<String, dynamic>.from(json['clarification'] as Map))
          : null,
    );
  }
}

/// Ask understood an action but needs one more thing before it can propose
/// it (e.g. which customer). See `Clarification` in
/// `services/runtime/app/schemas.py`.
class Clarification {
  Clarification({
    required this.kind,
    required this.field,
    required this.questionMd,
    this.candidates = const [],
    this.ref,
  });

  final String kind;
  final String field;
  final String questionMd;
  final List<String> candidates;
  final String? ref;

  factory Clarification.fromJson(Map<String, dynamic> json) {
    return Clarification(
      kind: (json['kind'] ?? '').toString(),
      field: (json['field'] ?? '').toString(),
      questionMd: (json['question_md'] ?? '').toString(),
      candidates: [
        if (json['candidates'] is List)
          for (final c in json['candidates'] as List) c.toString(),
      ],
      ref: json['ref']?.toString(),
    );
  }
}

/// The question again with the user's words for the thing replaced by the
/// picked candidate. Mirrors `withPicked` in
/// `apps/web/src/components/ask/ActionCard.tsx`.
String withPicked(String question, Clarification clarification, String name) {
  final ref = (clarification.ref ?? '').trim();
  if (ref.isNotEmpty) {
    final at = question.toLowerCase().indexOf(ref.toLowerCase());
    if (at >= 0) {
      return question.substring(0, at) +
          name +
          question.substring(at + ref.length);
    }
  }
  return '$question ($name)';
}

/// Which Books.xlsx sheet an answer's figures live on, from the cited paths.
/// The workbook is a projection; VAT answers cite both the returns and the
/// ledger folders, so VAT wins. Mirrors `workbookSheet` in
/// `apps/web/src/components/ask/AnswerCard.tsx`.
String workbookSheet(AskAnswer answer) {
  final hay = [
    for (final k in answer.keyNumbers) k.source,
    ...answer.citations,
  ].join('\n');
  if (hay.contains('VAT returns')) return 'VAT';
  if (hay.contains('Bank statements')) return 'Bank';
  if (hay.contains('_System/proposals') || hay.contains('02 Needs a look')) {
    return 'Proposals';
  }
  if (hay.contains('/Jobs') ||
      hay.contains('/Staff') ||
      hay.contains('/Timesheets')) {
    return 'Jobs';
  }
  if (hay.contains('/Vehicles') || hay.contains('/Mileage')) {
    return 'Vehicles';
  }
  if (hay.contains('/Payroll')) return 'Payroll';
  if (hay.contains('/contacts')) return 'Customers';
  if (hay.contains('_System/Ledger')) return 'Ledger';
  return 'Summary';
}

/// A proposed action from Ask (`services/runtime/app/actions.py`).
class ProposedAction {
  ProposedAction(this.raw);

  /// The JSON as the runtime sent it; posted back unchanged to approve.
  final Map<String, dynamic> raw;

  String get id => (raw['id'] ?? '').toString();
  String get kind => (raw['kind'] ?? '').toString();
  String get summaryMd => (raw['summary_md'] ?? '').toString();
  String get confirmText => (raw['confirm_text'] ?? '').toString();
  DateTime? get expiresAt => DateTime.tryParse('${raw['expires_at']}');
  List<String> get warnings {
    final preview = raw['preview'];
    final list = preview is Map ? preview['warnings'] : null;
    return [if (list is List) for (final w in list) w.toString()];
  }
}

/// One figure copied from the facts, with the file it came from.
class KeyNumber {
  KeyNumber({required this.label, required this.value, required this.source});

  final String label;
  final String value;
  final String source;

  factory KeyNumber.fromJson(Map<String, dynamic> json) {
    return KeyNumber(
      label: (json['label'] ?? '').toString(),
      value: (json['value'] ?? '').toString(),
      source: (json['source'] ?? '').toString(),
    );
  }
}

/// A next step: `open_review`, `open_vat`, `chase_supplier` or `none`.
class SuggestedAction {
  SuggestedAction({required this.label, required this.kind, this.arg});

  final String label;
  final String kind;
  final String? arg;

  factory SuggestedAction.fromJson(Map<String, dynamic> json) {
    return SuggestedAction(
      label: (json['label'] ?? '').toString(),
      kind: (json['kind'] ?? 'none').toString(),
      arg: json['arg']?.toString(),
    );
  }
}

/// One earlier turn sent as context with a new question (the runtime keeps the last six).
class AskTurn {
  AskTurn({required this.role, required this.text});

  /// `user` or `assistant`.
  final String role;
  final String text;

  Map<String, dynamic> toJson() => {'role': role, 'text': text};
}
