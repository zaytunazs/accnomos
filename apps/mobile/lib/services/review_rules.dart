/// Which waiting proposals a saved Autopilot rule matches.
///
/// Dart port of `apps/web/src/lib/review-rules.ts` (plus the VRN helpers
/// from `apps/web/src/lib/review-edit.ts` and `plainReason` from
/// `apps/web/src/lib/review-view.ts`). The matching test is identical to
/// the web's: same supplier key, purchase side, every check passed, same
/// VAT number and VAT treatment, gross within twice the usual. Kept free
/// of Flutter so `flutter test` covers it.
library;

/// Words the supplier key drops from the end (and a leading 'the').
const _trailing = {'ltd', 'limited', 'plc', 'llp', 'uk', 'co'};

/// 'Screwfix Direct Ltd.' → 'screwfix-direct'; "Sainsbury's" → 'sainsburys';
/// 'B&Q' → 'b-and-q' (autopilot.supplier_key).
String supplierKey(String name) {
  var s = name.toLowerCase().replaceAll('&', ' and ');
  s = s.replaceAll("'", '').replaceAll('’', '');
  final words = s
      .replaceAll(RegExp(r'[^a-z0-9]+'), ' ')
      .trim()
      .split(RegExp(r'\s+'))
      .where((w) => w.isNotEmpty)
      .toList();
  while (words.length > 1 && _trailing.contains(words.last)) {
    words.removeLast();
  }
  if (words.length > 1 && words.first == 'the') words.removeAt(0);
  return words.join('-');
}

/// UK VAT number shapes the runtime accepts
/// (`services/runtime/app/checks.py`). Empty means none printed.
String? normaliseVrn(String? raw) {
  if (raw == null) return null;
  var s = raw
      .toUpperCase()
      .replaceAll(RegExp(r'[\s.\-]'), '')
      .replaceFirst(RegExp(r'^VAT(REG)?(NO|NUMBER)?:?'), '');
  if (s.isEmpty) return null;
  if (RegExp(r'^\d+$').hasMatch(s) && (s.length == 9 || s.length == 12)) {
    s = 'GB$s';
  }
  return s;
}

/// True when [raw] is empty (no number printed) or one of the accepted
/// shapes: GB/XI with 9 or 12 digits, or GD/HA with 3 digits.
bool vrnLooksValid(String raw) {
  final s = normaliseVrn(raw);
  if (s == null) return true;
  return RegExp(r'^(GB|XI)(\d{9}|\d{12}|(GD|HA)\d{3})$').hasMatch(s);
}

/// Checker reasons arrive as "CODE: plain-English note" — show the note,
/// never the raw code.
String plainReason(String reason) {
  return reason.replaceFirst(RegExp(r'^[A-Z][A-Z0-9_]*:\s*'), '');
}

/// VAT codes on the expense lines (or the sales lines), e.g. ['S'].
/// `journal` holds raw `journal_draft` maps; `sale` mirrors a
/// `sales_invoice` document type.
List<String> vatCodesOfJournal(List journal, bool sale) {
  final codes = <String>{};
  for (final entry in journal) {
    if (entry is! Map) continue;
    final debit = _pence(entry['debit_pence']);
    final credit = _pence(entry['credit_pence']);
    final relevant = sale ? credit > 0 : debit > 0;
    if (!relevant) continue;
    final account = (entry['account'] ?? '').toString();
    if (account.startsWith('2200')) continue;
    final code = entry['vat_code']?.toString();
    if (code != null && code.isNotEmpty) codes.add(code);
  }
  return codes.toList()..sort();
}

/// First expense account in `journal_draft` (a debit outside VAT control),
/// used by [ruleEdits]. Null when the draft carries none.
String? expenseAccountOfJournal(List journal) {
  for (final entry in journal) {
    if (entry is! Map) continue;
    if (_pence(entry['debit_pence']) <= 0) continue;
    final account = (entry['account'] ?? '').toString();
    if (account.startsWith('2200')) continue;
    if (account.isEmpty) continue;
    return account;
  }
  return null;
}

int _pence(Object? value) {
  if (value is num) return value.round();
  return 0;
}

/// A saved Autopilot rule (`services/runtime/app/autopilot.py`), as
/// `GET /books/rules` returns it.
class ReviewRule {
  const ReviewRule({
    required this.supplierKey,
    required this.supplierName,
    required this.category,
    required this.account,
    required this.vatCode,
    required this.side,
    required this.typicalGrossPence,
    required this.vrn,
  });

  final String supplierKey;
  final String supplierName;
  final String category;
  final String? account;
  final String? vatCode;
  final String side;
  final int typicalGrossPence;
  final String? vrn;

  factory ReviewRule.fromJson(Map<String, dynamic> json) {
    int pence(Object? value) {
      if (value is num) return value.round();
      return int.tryParse(value.toString()) ?? 0;
    }

    return ReviewRule(
      supplierKey: (json['supplier_key'] ?? '').toString(),
      supplierName: (json['supplier_name'] ?? '').toString(),
      category: (json['category'] ?? '').toString(),
      account: json['account']?.toString(),
      vatCode: json['vat_code']?.toString(),
      side: (json['side'] ?? 'purchase').toString(),
      typicalGrossPence: pence(json['typical_gross_pence']),
      vrn: json['vrn']?.toString(),
    );
  }
}

/// The proposal fields the rule test reads. Built from a runtime proposal
/// in `Proposal.fromRuntime`, or from sample data for signed-out cards.
class ProposalRuleView {
  const ProposalRuleView({
    required this.supplierName,
    required this.docType,
    required this.mileageClaim,
    required this.statusProposed,
    required this.checksOk,
    required this.supplierVrn,
    required this.vatCodes,
    required this.grossPence,
    required this.categoryGuess,
    required this.expenseAccount,
  });

  final String supplierName;
  final String docType;
  final bool mileageClaim;
  final bool statusProposed;
  final bool checksOk;
  final String? supplierVrn;
  final List<String> vatCodes;
  final int grossPence;
  final String categoryGuess;
  final String? expenseAccount;

  ProposalRuleView copyWith({
    String? supplierName,
    String? docType,
    bool? mileageClaim,
    bool? statusProposed,
    bool? checksOk,
    String? supplierVrn,
    List<String>? vatCodes,
    int? grossPence,
    String? categoryGuess,
    String? expenseAccount,
  }) {
    return ProposalRuleView(
      supplierName: supplierName ?? this.supplierName,
      docType: docType ?? this.docType,
      mileageClaim: mileageClaim ?? this.mileageClaim,
      statusProposed: statusProposed ?? this.statusProposed,
      checksOk: checksOk ?? this.checksOk,
      supplierVrn: supplierVrn ?? this.supplierVrn,
      vatCodes: vatCodes ?? this.vatCodes,
      grossPence: grossPence ?? this.grossPence,
      categoryGuess: categoryGuess ?? this.categoryGuess,
      expenseAccount: expenseAccount ?? this.expenseAccount,
    );
  }
}

/// The rule this proposal fully matches, or null. Same test as the web:
/// newest saved rule for the supplier, purchase side, not a sales invoice
/// or mileage claim, still proposed with every check passed, same VAT
/// number and VAT treatment, gross within twice the usual.
ReviewRule? matchingRule(ProposalRuleView p, List<ReviewRule> rules) {
  final key = supplierKey(p.supplierName);
  ReviewRule? rule;
  for (var i = rules.length - 1; i >= 0; i--) {
    if (rules[i].supplierKey == key) {
      rule = rules[i];
      break;
    }
  }
  if (rule == null) return null;
  if (rule.side != 'purchase') return null;
  if (p.docType == 'sales_invoice' || p.mileageClaim) return null;
  if (!p.statusProposed || !p.checksOk) return null;
  if (normaliseVrn(p.supplierVrn) != rule.vrn) return null;
  final codes = [...p.vatCodes]..sort();
  final codesKey = codes.isEmpty ? null : codes.join(',');
  if (codesKey != rule.vatCode) return null;
  if (p.grossPence <= 0 || p.grossPence > 2 * rule.typicalGrossPence) {
    return null;
  }
  return rule;
}

/// 'Do the same as the approval that made the rule', sending only what
/// differs. Null when the proposal already matches the rule.
Map<String, String>? ruleEdits(ProposalRuleView p, ReviewRule rule) {
  final edits = <String, String>{};
  if (rule.category.isNotEmpty && rule.category != p.categoryGuess) {
    edits['category'] = rule.category;
  }
  if (rule.account != null &&
      rule.account!.isNotEmpty &&
      rule.account != p.expenseAccount) {
    edits['account'] = rule.account!;
  }
  return edits.isEmpty ? null : edits;
}

/// Human line for a rule match on the card, mirroring the web notice.
String ruleMatchLine(ReviewRule rule, int typicalGrossPence) {
  final name =
      rule.supplierName.isNotEmpty ? rule.supplierName : rule.supplierKey;
  final vat = rule.vatCode == null ? 'none' : rule.vatCode!;
  return 'Matches your Autopilot rule for $name: ${rule.category}, '
      'VAT $vat, usual ${formatPence(typicalGrossPence)}. '
      'At L1 it waits for you.';
}

/// Format integer pence as pounds ('£12.34').
String formatPence(int pence) => '£${(pence / 100).toStringAsFixed(2)}';
