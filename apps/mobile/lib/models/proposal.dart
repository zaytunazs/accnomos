/// Static sample proposals for the Review screen. Demo data only.
///
/// Lifecycle of a proposed bookkeeping entry.
enum ProposalStatus {
  /// Ordinary receipt or invoice waiting for approval.
  proposed,

  /// Something looks off and needs a human decision.
  needsALook,

  /// Spoken note with no VAT receipt attached.
  voiceNote,
}

/// One proposed entry shown as a review card.
class Proposal {
  const Proposal({
    required this.id,
    required this.supplier,
    required this.total,
    required this.date,
    required this.paidBy,
    required this.confidence,
    required this.source,
    required this.category,
    required this.status,
    this.net,
    this.vat,
    this.vatNumber,
    this.reviewerNote,
    this.verifierNote,
    this.reason,
    this.quote,
  });

  final String id;
  final String supplier;
  final double total;
  final String date;
  final String paidBy;

  /// 0-1 confidence in the reading.
  final double confidence;

  /// Either 'Read on your machine' or 'Read by Muse Spark'.
  final String source;
  final String category;
  final double? net;
  final double? vat;
  final String? vatNumber;
  final String? reviewerNote;
  final String? verifierNote;
  final ProposalStatus status;

  /// Set when [status] is [ProposalStatus.needsALook].
  final String? reason;

  /// Set when [status] is [ProposalStatus.voiceNote].
  final String? quote;

  /// Three fictional sample items for demos.
  static const List<Proposal> samples = [
    Proposal(
      id: 'screwfix-001',
      supplier: 'Screwfix',
      total: 38.47,
      date: '21 Oct 2026',
      paidBy: 'Business debit card',
      confidence: 0.94,
      source: 'Read on your machine',
      category: 'Tools & small equipment',
      net: 32.06,
      vat: 6.41,
      vatNumber: 'GB 232 5551 12',
      reviewerNote: 'Screwfix receipt for fixings and drill bits for the Croydon job.',
      verifierNote: 'Verifier agrees · all 5 fields match.',
      status: ProposalStatus.proposed,
    ),
    Proposal(
      id: 'travis-perkins-tp-88213',
      supplier: 'Travis Perkins',
      total: 212.40,
      date: '16 Oct 2026',
      paidBy: 'Business debit card',
      confidence: 0.61,
      source: 'Read by Muse Spark',
      category: 'Materials',
      net: 177.00,
      vat: 35.40,
      vatNumber: 'GB 440 1234 55',
      reviewerNote: 'Invoice TP-88213 for timber and sheet materials.',
      status: ProposalStatus.needsALook,
      reason:
          'Looks like a duplicate of a receipt you approved on 14 Oct '
          '(same supplier, same total, same invoice number TP-88213).',
    ),
    Proposal(
      id: 'parking-croydon-001',
      supplier: 'Parking',
      total: 4.00,
      date: '20 Oct 2026',
      paidBy: 'Cash',
      confidence: 0.81,
      source: 'Read on your machine',
      category: 'Travel & parking',
      status: ProposalStatus.voiceNote,
      quote: 'Paid four pounds cash for parking at the Croydon job',
    ),
  ];
}
