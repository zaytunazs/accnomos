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

  /// Build a proposal from the runtime `/extract` response shape:
  /// `extracted` {supplier_name, gross_total, net_total, vat_total, date
  /// (ISO), supplier_vat_number, category_guess, confidence (0-1),
  /// payment_method, card_last4}, `status` ("proposed"|"needs_a_look"),
  /// `reasons` (list of strings), `model`, and `checks`
  /// (list of {code, ok, message}).
  factory Proposal.fromRuntime(Map<String, dynamic> json) {
    final extracted = json['extracted'] is Map
        ? Map<String, dynamic>.from(json['extracted'] as Map)
        : <String, dynamic>{};

    final reasons = <String>[];
    if (json['reasons'] is List) {
      for (final r in json['reasons'] as List) {
        reasons.add(r.toString());
      }
    }

    final checks = <Map<String, dynamic>>[];
    if (json['checks'] is List) {
      for (final c in json['checks'] as List) {
        if (c is Map) checks.add(Map<String, dynamic>.from(c));
      }
    }

    final statusRaw = (json['status'] as String?) ?? 'proposed';
    final status = statusRaw == 'needs_a_look'
        ? ProposalStatus.needsALook
        : ProposalStatus.proposed;

    final model = (json['model'] as String?) ?? '';
    final source = model.startsWith('local:')
        ? 'Read on your machine'
        : 'Read by Muse Spark';

    String? reviewerNote;
    if (checks.isNotEmpty) {
      final passed = checks.where((c) => c['ok'] == true).length;
      String? firstFailure;
      for (final c in checks) {
        if (c['ok'] != true) {
          final message =
              (c['message'] ?? c['code'] ?? '').toString().trim();
          if (message.isNotEmpty) {
            firstFailure = message;
            break;
          }
        }
      }
      reviewerNote = 'Checks: $passed of ${checks.length} passed'
          '${firstFailure != null ? ' · $firstFailure' : ''}';
    }

    final supplier =
        (extracted['supplier_name'] as String?)?.trim() ?? '';
    final paymentMethod =
        (extracted['payment_method'] as String?)?.trim() ?? '';
    final cardLast4 = extracted['card_last4']?.toString().trim() ?? '';
    final String paidBy;
    if (paymentMethod == 'card' && cardLast4.isNotEmpty) {
      paidBy = 'Card ···· $cardLast4';
    } else if (paymentMethod == 'card') {
      paidBy = 'Card';
    } else if (paymentMethod == 'cash') {
      paidBy = 'Cash';
    } else if (paymentMethod.isNotEmpty) {
      paidBy = paymentMethod;
    } else {
      paidBy = 'Unknown';
    }

    final vatNumber =
        extracted['supplier_vat_number']?.toString().trim() ?? '';
    final category =
        (extracted['category_guess'] as String?)?.trim() ?? '';

    return Proposal(
      id: 'runtime-${DateTime.now().millisecondsSinceEpoch}',
      supplier: supplier.isNotEmpty ? supplier : 'Unknown supplier',
      total: _toDouble(extracted['gross_total']) ?? 0,
      date: _displayDate(extracted['date']),
      paidBy: paidBy,
      confidence: _toDouble(extracted['confidence']) ?? 0,
      source: source,
      category: category.isNotEmpty ? category : 'Uncategorised',
      status: status,
      net: _toDouble(extracted['net_total']),
      vat: _toDouble(extracted['vat_total']),
      vatNumber: vatNumber.isNotEmpty ? vatNumber : null,
      reviewerNote: reviewerNote,
      verifierNote: '',
      reason: reasons.isNotEmpty ? reasons.join(' · ') : null,
    );
  }

  static double? _toDouble(Object? value) {
    if (value is num) return value.toDouble();
    if (value is String) return double.tryParse(value.trim());
    return null;
  }

  static String _displayDate(Object? iso) {
    final text = iso?.toString().trim() ?? '';
    if (text.isEmpty) return 'Unknown date';
    try {
      final d = DateTime.parse(text);
      const months = [
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
      ];
      return '${d.day} ${months[d.month - 1]} ${d.year}';
    } catch (_) {
      return text;
    }
  }

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
