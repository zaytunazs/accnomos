/// One thread from `POST /mail/triage` (services/runtime/app/triage.py).
/// Summaries and suggested replies come from the runtime; the phone never
/// calls a model itself.
class TriageThread {
  TriageThread({
    required this.conversationId,
    required this.messageId,
    required this.subject,
    required this.fromName,
    required this.fromAddress,
    required this.summary,
    required this.needsReply,
    this.suggestedReply,
    this.fallbackReason,
  });

  final String conversationId;
  final String messageId;
  final String subject;
  final String fromName;
  final String fromAddress;
  final String summary;
  final bool needsReply;
  final String? suggestedReply;
  final String? fallbackReason;

  String get who => fromName.isNotEmpty ? fromName : fromAddress;

  factory TriageThread.fromJson(Map<String, dynamic> json) => TriageThread(
        conversationId: (json['conversation_id'] ?? '').toString(),
        messageId: (json['message_id'] ?? '').toString(),
        subject: (json['subject'] ?? '').toString(),
        fromName: (json['from_name'] ?? '').toString(),
        fromAddress: (json['from_address'] ?? '').toString(),
        summary: (json['summary'] ?? '').toString(),
        needsReply: json['needs_reply'] == true,
        suggestedReply: json['suggested_reply']?.toString(),
        fallbackReason: json['fallback_reason']?.toString(),
      );

  static List<TriageThread> listFromJson(Object? raw) {
    if (raw is! List) return const [];
    return [
      for (final t in raw)
        if (t is Map) TriageThread.fromJson(Map<String, dynamic>.from(t)),
    ];
  }

  /// Labelled demo threads for the signed-out card. Fictional.
  static List<TriageThread> get samples => [
        TriageThread(
          conversationId: 'sample-1',
          messageId: 'sample-1',
          subject: 'Re: Invoice INV-0041',
          fromName: 'Bramblewood Ltd',
          fromAddress: 'accounts@bramblewood.example',
          summary: 'Bramblewood ask for another week to pay INV-0041.',
          needsReply: true,
          suggestedReply:
              'Thanks for letting me know. I can give you until Friday; '
              'please confirm the payment date.',
        ),
        TriageThread(
          conversationId: 'sample-2',
          messageId: 'sample-2',
          subject: 'Your VAT return is due',
          fromName: 'HMRC',
          fromAddress: 'no-reply@hmrc.gov.uk',
          summary: 'A reminder that the Jul–Sep VAT return is due.',
          needsReply: false,
        ),
      ];
}
