/// PayPal on the phone: Sync PayPal, the tie-out, disputes and bill pay.
/// Shapes follow the runtime's pydantic models (services/runtime/app/
/// paypal_sync.py, paypal_disputes.py, billpay.py) and the web's types
/// (apps/web/src/lib/runtime.ts, disputes.ts, billpay.ts). Every amount is
/// integer pence worked out by the runtime; the phone only formats it.
/// Parsing is forgiving: a missing or wrong-typed field becomes a safe
/// default rather than an exception, so an older runtime still renders.
library;

int _pence(Object? v) => v is num ? v.round() : (int.tryParse('${v ?? ''}') ?? 0);

int? _penceOrNull(Object? v) =>
    v == null ? null : (v is num ? v.round() : int.tryParse('$v'));

String _str(Object? v) => v == null ? '' : '$v';

String? _strOrNull(Object? v) {
  if (v == null) return null;
  final s = '$v';
  return s.isEmpty ? null : s;
}

bool _bool(Object? v) => v == true;

List<String> _strings(Object? v) =>
    v is List ? [for (final x in v) if (x != null) '$x'] : const [];

List<Map<String, dynamic>> _maps(Object? v) => v is List
    ? [for (final x in v) if (x is Map) Map<String, dynamic>.from(x)]
    : const [];

Map<String, dynamic>? _map(Object? v) =>
    v is Map ? Map<String, dynamic>.from(v) : null;

/// One line of what approving posts, worked out by code.
class JournalLine {
  const JournalLine({
    required this.account,
    this.debitPence = 0,
    this.creditPence = 0,
    this.vatCode,
  });

  factory JournalLine.fromJson(Map<String, dynamic> j) => JournalLine(
        account: _str(j['account']),
        debitPence: _pence(j['debit_pence']),
        creditPence: _pence(j['credit_pence']),
        vatCode: _strOrNull(j['vat_code']),
      );

  final String account;
  final int debitPence;
  final int creditPence;
  final String? vatCode;

  static List<JournalLine> list(Object? v) =>
      [for (final m in _maps(v)) JournalLine.fromJson(m)];
}

/// VAT codes, as the web's PayPalSync labels them.
const paypalVatLabels = {
  'S': 'Standard 20%',
  'R': 'Reduced 5%',
  'Z': 'Zero rated',
  'E': 'Exempt',
  'N': 'No VAT to reclaim',
  'O': 'Outside the scope of VAT',
};

/// The VAT an owner can give a sale with no invoice (no "N": that is for
/// purchases).
const paypalSaleVatCodes = ['S', 'R', 'Z', 'E', 'O'];

/// The VAT a PayPal purchase can take.
const paypalPurchaseVatCodes = ['S', 'R', 'Z', 'E', 'N'];

/// The cost accounts a PayPal purchase can go to (journal.py
/// CATEGORY_ACCOUNTS and Sundry), as on the web.
const paypalCostAccounts = [
  '5000 Materials',
  '5100 Tools & small equipment',
  '6200 Advertising',
  '7100 Rent',
  '7200 Utilities',
  '7300 Motor expenses',
  '7400 Travel',
  '7410 Subsistence',
  '7500 Office supplies',
  '7510 Software & subscriptions',
  '7520 Postage',
  '7550 Telephone & internet',
  '7600 Professional fees',
  '7700 Insurance',
  '7900 Bank charges',
  '7999 Sundry expenses',
];

const paypalKindLabels = {
  'invoice': 'Invoice payment',
  'sale': 'Sale',
  'expense': 'Purchase',
  'fee': 'PayPal fee',
  'withdrawal': 'Withdrawal to bank',
  'deposit': 'Added from bank',
  'refund': 'Refund or reversal',
  'other': 'Not posted',
};

const paypalStatusLabels = {
  'approved': 'approved',
  'rejected': 'rejected',
  'already': 'already in your books',
  'info': 'not posted',
  'proposed': 'waiting',
};

/// One synced PayPal transaction (`SyncItem`).
class PayPalSyncItem {
  const PayPalSyncItem({
    required this.transactionId,
    required this.date,
    required this.kind,
    required this.status,
    required this.name,
    this.items = const [],
    this.currency = 'GBP',
    this.grossPence = 0,
    this.feePence = 0,
    this.netPence = 0,
    this.invoice,
    this.account,
    this.vatCode,
    this.codedBy,
    this.notes = const [],
    this.journal = const [],
    this.rejectReason,
  });

  factory PayPalSyncItem.fromJson(Map<String, dynamic> j) => PayPalSyncItem(
        transactionId: _str(j['transaction_id']),
        date: _str(j['date']),
        kind: _str(j['kind']).isEmpty ? 'other' : _str(j['kind']),
        status: _str(j['status']).isEmpty ? 'info' : _str(j['status']),
        name: _str(j['name']),
        items: _strings(j['items']),
        currency: _str(j['currency']).isEmpty ? 'GBP' : _str(j['currency']),
        grossPence: _pence(j['gross_pence']),
        feePence: _pence(j['fee_pence']),
        netPence: _pence(j['net_pence']),
        invoice: _strOrNull(j['invoice']),
        account: _strOrNull(j['account']),
        vatCode: _strOrNull(j['vat_code']),
        codedBy: _strOrNull(j['coded_by']),
        notes: _strings(j['notes']),
        journal: JournalLine.list(j['journal']),
        rejectReason: _strOrNull(j['reject_reason']),
      );

  final String transactionId;
  final String date;

  /// invoice | sale | expense | fee | withdrawal | deposit | refund | other
  final String kind;

  /// proposed | approved | rejected | already | info
  final String status;
  final String name;
  final List<String> items;
  final String currency;

  /// Signed: money in is positive.
  final int grossPence;
  final int feePence;
  final int netPence;
  final String? invoice;
  final String? account;
  final String? vatCode;
  final String? codedBy;
  final List<String> notes;
  final List<JournalLine> journal;
  final String? rejectReason;

  bool get waiting => status == 'proposed';

  /// A sale with no invoice in VAT-registered books: the runtime leaves its
  /// VAT empty and refuses to post it until the owner picks one.
  bool get needsVatChoice => kind == 'sale' && waiting && vatCode == null;

  /// A purchase: the owner may change its account and VAT.
  bool get editable => kind == 'expense';

  String get kindLabel => paypalKindLabels[kind] ?? 'Not posted';
  String get statusLabel => paypalStatusLabels[status] ?? status;
}

/// `GET /payments/paypal/sync`.
class PayPalSyncView {
  const PayPalSyncView({
    required this.available,
    this.reason,
    this.source,
    this.sample = false,
    this.lastSyncedAt,
    this.items = const [],
  });

  factory PayPalSyncView.fromJson(Map<String, dynamic> j) => PayPalSyncView(
        available: _bool(j['available']),
        reason: _strOrNull(j['reason']),
        source: _strOrNull(j['source']),
        sample: _bool(j['sample']),
        lastSyncedAt: _strOrNull(j['last_synced_at']),
        items: [for (final m in _maps(j['items'])) PayPalSyncItem.fromJson(m)],
      );

  final bool available;
  final String? reason;
  final String? source;

  /// The demo's sample history, not a real PayPal account.
  final bool sample;
  final String? lastSyncedAt;
  final List<PayPalSyncItem> items;

  List<PayPalSyncItem> get waiting => [for (final i in items) if (i.waiting) i];
  List<PayPalSyncItem> get rest => [for (final i in items) if (!i.waiting) i];

  PayPalSyncView copyWith({List<PayPalSyncItem>? items, String? lastSyncedAt}) =>
      PayPalSyncView(
        available: available,
        reason: reason,
        source: source,
        sample: sample,
        lastSyncedAt: lastSyncedAt ?? this.lastSyncedAt,
        items: items ?? this.items,
      );
}

/// `POST /payments/paypal/sync`.
class PayPalSyncResult {
  const PayPalSyncResult({
    this.sample = false,
    this.newCount = 0,
    this.pending = 0,
    this.items = const [],
  });

  factory PayPalSyncResult.fromJson(Map<String, dynamic> j) => PayPalSyncResult(
        sample: _bool(j['sample']),
        newCount: _pence(j['new']),
        pending: _pence(j['pending']),
        items: [for (final m in _maps(j['items'])) PayPalSyncItem.fromJson(m)],
      );

  final bool sample;
  final int newCount;

  /// Still pending at PayPal: picked up by a later sync.
  final int pending;
  final List<PayPalSyncItem> items;

  /// "2 new from PayPal · 3 waiting for you · 1 still pending at PayPal".
  String get summary {
    final waitingNow = items.where((i) => i.waiting).length;
    return '${newCount == 0 ? 'Nothing new' : '$newCount new'} from PayPal'
        ' · $waitingNow waiting for you'
        '${pending > 0 ? ' · $pending still pending at PayPal' : ''}';
  }
}

/// `GET /payments/paypal/tieout`: PayPal's own balance against 1240 PayPal
/// clearing, the gap explained. Read-only.
class PayPalTieOut {
  const PayPalTieOut({
    required this.available,
    this.reason,
    this.paypalPence,
    this.paypalAsOf,
    this.booksPence = 0,
    this.differencePence,
    this.waitingPence = 0,
    this.notPostedPence = 0,
    this.unexplainedPence,
    this.notes = const [],
  });

  factory PayPalTieOut.fromJson(Map<String, dynamic> j) => PayPalTieOut(
        available: _bool(j['available']),
        reason: _strOrNull(j['reason']),
        paypalPence: _penceOrNull(j['paypal_pence']),
        paypalAsOf: _strOrNull(j['paypal_as_of']),
        booksPence: _pence(j['books_pence']),
        differencePence: _penceOrNull(j['difference_pence']),
        waitingPence: _pence(j['waiting_pence']),
        notPostedPence: _pence(j['not_posted_pence']),
        unexplainedPence: _penceOrNull(j['unexplained_pence']),
        notes: _strings(j['notes']),
      );

  final bool available;
  final String? reason;
  final int? paypalPence;

  /// When PayPal last refreshed its balance (it lags): shown beside it.
  final String? paypalAsOf;
  final int booksPence;
  final int? differencePence;
  final int waitingPence;
  final int notPostedPence;
  final int? unexplainedPence;
  final List<String> notes;

  bool get shown => available && paypalPence != null;
  bool get ties => unexplainedPence == 0;
}

/// `GET /payments/paypal/fees`.
class PayPalFees {
  const PayPalFees({
    this.feesPence = 0,
    this.transactions = 0,
    this.receivedPence = 0,
    this.feesInBooksPence = 0,
    this.syncedThrough,
  });

  factory PayPalFees.fromJson(Map<String, dynamic> j) => PayPalFees(
        feesPence: _pence(j['fees_pence']),
        transactions: _pence(j['transactions']),
        receivedPence: _pence(j['received_pence']),
        feesInBooksPence: _pence(j['fees_in_books_pence']),
        syncedThrough: _strOrNull(j['synced_through']),
      );

  final int feesPence;
  final int transactions;
  final int receivedPence;
  final int feesInBooksPence;
  final String? syncedThrough;
}

/// One provider from `GET /payments/online/providers`.
class PayProviderStatus {
  const PayProviderStatus({
    required this.provider,
    required this.label,
    this.available = false,
    this.reason,
    this.testMode = false,
    this.connected = false,
    this.account,
    this.connectedAt,
  });

  factory PayProviderStatus.fromJson(Map<String, dynamic> j) => PayProviderStatus(
        provider: _str(j['provider']),
        label: _str(j['label']).isEmpty ? _str(j['provider']) : _str(j['label']),
        available: _bool(j['available']),
        reason: _strOrNull(j['reason']),
        testMode: _bool(j['test_mode']),
        connected: _bool(j['connected']),
        account: _strOrNull(j['account']),
        connectedAt: _strOrNull(j['connected_at']),
      );

  final String provider;
  final String label;
  final bool available;
  final String? reason;
  final bool testMode;
  final bool connected;
  final String? account;
  final String? connectedAt;

  /// The PayPal row (`paypal`, not PayPal.me) from a provider list, or null.
  static PayProviderStatus? paypal(List<PayProviderStatus> all) {
    for (final p in all) {
      if (p.provider == 'paypal') return p;
    }
    return null;
  }
}

// --------------------------------------------------------------------------
// Disputes
// --------------------------------------------------------------------------

const disputeStatusLabels = {
  'OPEN': 'Open',
  'WAITING_FOR_SELLER_RESPONSE': 'Waiting for your answer',
  'WAITING_FOR_BUYER_RESPONSE': 'Waiting for the customer',
  'UNDER_REVIEW': 'PayPal is reviewing it',
  'RESOLVED': 'Closed',
  'OTHER': 'Open',
};

/// The evidence Accnomos built for a dispute (`EvidenceProposal`).
class DisputeEvidence {
  const DisputeEvidence({
    required this.disputeId,
    this.invoice = '',
    this.notes = '',
    this.fallbackReason,
    this.status = 'proposed',
    this.builtAt,
    this.sentAt,
    this.sentBy,
    this.demo = false,
  });

  factory DisputeEvidence.fromJson(Map<String, dynamic> j) => DisputeEvidence(
        disputeId: _str(j['dispute_id']),
        invoice: _str(j['invoice']),
        notes: _str(j['notes']),
        fallbackReason: _strOrNull(j['fallback_reason']),
        status: _str(j['status']).isEmpty ? 'proposed' : _str(j['status']),
        builtAt: _strOrNull(j['built_at']),
        sentAt: _strOrNull(j['sent_at']),
        sentBy: _strOrNull(j['sent_by']),
        demo: _bool(j['demo']),
      );

  final String disputeId;
  final String invoice;

  /// The response PayPal gets, checked by code against the books.
  final String notes;

  /// Why code wrote the response instead of the AI.
  final String? fallbackReason;

  /// proposed | sent
  final String status;
  final String? builtAt;
  final String? sentAt;
  final String? sentBy;

  /// A demo's sample: recorded as sent without calling PayPal.
  final bool demo;

  bool get sent => status == 'sent';
}

/// The reversing entry after a lost dispute (`ReversalProposal`).
class DisputeReversal {
  const DisputeReversal({
    this.paymentRecord = '',
    this.amountPence = 0,
    this.refundedPence,
    this.canPost = false,
    this.reason,
    this.journal = const [],
  });

  factory DisputeReversal.fromJson(Map<String, dynamic> j) => DisputeReversal(
        paymentRecord: _str(j['payment_record']),
        amountPence: _pence(j['amount_pence']),
        refundedPence: _penceOrNull(j['refunded_pence']),
        canPost: _bool(j['can_post']),
        reason: _strOrNull(j['reason']),
        journal: JournalLine.list(j['journal']),
      );

  final String paymentRecord;
  final int amountPence;
  final int? refundedPence;
  final bool canPost;
  final String? reason;
  final List<JournalLine> journal;
}

/// One PayPal dispute (`DisputeRow`).
class PayPalDispute {
  const PayPalDispute({
    required this.disputeId,
    this.sample = false,
    this.reason = '',
    this.reasonText = '',
    this.status = 'OPEN',
    this.amountPence,
    this.respondBy,
    this.opened,
    this.invoice,
    this.customer,
    this.canSendEvidence = false,
    this.outcome,
    this.lost = false,
    this.proposal,
    this.reversal,
  });

  factory PayPalDispute.fromJson(Map<String, dynamic> j) {
    final proposal = _map(j['proposal']);
    final reversal = _map(j['reversal']);
    return PayPalDispute(
      disputeId: _str(j['dispute_id']),
      sample: _bool(j['sample']),
      reason: _str(j['reason']),
      reasonText: _str(j['reason_text']),
      status: _str(j['status']).isEmpty ? 'OPEN' : _str(j['status']),
      amountPence: _penceOrNull(j['amount_pence']),
      respondBy: _strOrNull(j['respond_by']),
      opened: _strOrNull(j['opened']),
      invoice: _strOrNull(j['invoice']),
      customer: _strOrNull(j['customer']),
      canSendEvidence: _bool(j['can_send_evidence']),
      outcome: _strOrNull(j['outcome']),
      lost: _bool(j['lost']),
      proposal: proposal == null ? null : DisputeEvidence.fromJson(proposal),
      reversal: reversal == null ? null : DisputeReversal.fromJson(reversal),
    );
  }

  final String disputeId;

  /// The demo's sample dispute: never sent to PayPal.
  final bool sample;
  final String reason;

  /// "says the item was not received", completing "The customer …".
  final String reasonText;
  final String status;
  final int? amountPence;
  final String? respondBy;
  final String? opened;

  /// The Accnomos invoice it matched; null: not a payment Accnomos knows.
  final String? invoice;
  final String? customer;
  final bool canSendEvidence;
  final String? outcome;
  final bool lost;
  final DisputeEvidence? proposal;
  final DisputeReversal? reversal;

  String get statusLabel => disputeStatusLabels[status] ?? status;
  bool get waitingForYou => status == 'WAITING_FOR_SELLER_RESPONSE';
}

/// `GET /payments/online/paypal/disputes`.
class PayPalDisputeList {
  const PayPalDisputeList({
    this.connected = false,
    this.disputes = const [],
    this.problem,
  });

  factory PayPalDisputeList.fromJson(Map<String, dynamic> j) => PayPalDisputeList(
        connected: _bool(j['connected']),
        disputes: [for (final m in _maps(j['disputes'])) PayPalDispute.fromJson(m)],
        problem: _strOrNull(j['problem']),
      );

  final bool connected;
  final List<PayPalDispute> disputes;

  /// PayPal could not be asked, in a sentence.
  final String? problem;
}

// --------------------------------------------------------------------------
// Bill pay
// --------------------------------------------------------------------------

const payoutStatusLabels = {
  'sending': 'Sending to PayPal',
  'pending': 'PayPal is processing it',
  'unclaimed': 'Waiting for the supplier to claim it',
  'paid': 'Paid and posted',
  'failed': 'Not paid',
  'unknown': "Waiting for PayPal's answer",
};

/// A payment to a supplier through PayPal (`Payout`).
class BillPayout {
  const BillPayout({
    required this.id,
    this.eventId = '',
    this.supplier = '',
    this.reference,
    this.amountPence = 0,
    this.receiver = '',
    this.via = 'owner',
    this.status = 'unknown',
    this.detail,
    this.feePence,
    this.problem,
    this.createdAt,
  });

  factory BillPayout.fromJson(Map<String, dynamic> j) => BillPayout(
        id: _str(j['id']),
        eventId: _str(j['event_id']),
        supplier: _str(j['supplier']),
        reference: _strOrNull(j['reference']),
        amountPence: _pence(j['amount_pence']),
        receiver: _str(j['receiver']),
        via: _str(j['via']).isEmpty ? 'owner' : _str(j['via']),
        status: _str(j['status']).isEmpty ? 'unknown' : _str(j['status']),
        detail: _strOrNull(j['detail']),
        feePence: _penceOrNull(j['fee_pence']),
        problem: _strOrNull(j['problem']),
        createdAt: _strOrNull(j['created_at']),
      );

  final String id;
  final String eventId;
  final String supplier;
  final String? reference;
  final int amountPence;
  final String receiver;

  /// owner | autopilot
  final String via;
  final String status;
  final String? detail;
  final int? feePence;
  final String? problem;
  final String? createdAt;

  String get statusLabel => payoutStatusLabels[status] ?? status;
}

/// An unpaid bill (`Bill`).
class BillPayBill {
  const BillPayBill({
    required this.eventId,
    this.contactId = '',
    this.supplier = '',
    this.reference,
    this.dueDate = '',
    this.daysOverdue = 0,
    this.owedPence = 0,
    this.plan,
    this.payeeEmail,
    this.dueNow = false,
    this.canPay = false,
    this.blocks = const [],
    this.warnings = const [],
    this.changedDetails = const [],
    this.payout,
    this.approval,
  });

  factory BillPayBill.fromJson(Map<String, dynamic> j) {
    final payout = _map(j['payout']);
    final approval = _map(j['approval']);
    return BillPayBill(
      eventId: _str(j['event_id']),
      contactId: _str(j['contact_id']),
      supplier: _str(j['supplier']),
      reference: _strOrNull(j['reference']),
      dueDate: _str(j['due_date']),
      daysOverdue: _pence(j['days_overdue']),
      owedPence: _pence(j['owed_pence']),
      plan: _strOrNull(j['plan']),
      payeeEmail: _strOrNull(j['payee_email']),
      dueNow: _bool(j['due_now']),
      canPay: _bool(j['can_pay']),
      blocks: _strings(j['blocks']),
      warnings: _strings(j['warnings']),
      changedDetails: _strings(j['changed_details']),
      payout: payout == null ? null : BillPayout.fromJson(payout),
      approval: approval == null ? null : BillPayApproval.fromJson(approval),
    );
  }

  final String eventId;
  final String contactId;
  final String supplier;
  final String? reference;
  final String dueDate;

  /// Negative: not due yet.
  final int daysOverdue;
  final int owedPence;

  /// paypal | not_paypal | null (not chosen)
  final String? plan;
  final String? payeeEmail;
  final bool dueNow;
  final bool canPay;
  final List<String> blocks;
  final List<String> warnings;

  /// Changed payment details on the bill: the owner must say they checked
  /// with the supplier before paying.
  final List<String> changedDetails;
  final BillPayout? payout;

  /// "Approve now, pay on due date", unless cancelled.
  final BillPayApproval? approval;

  /// Approved in advance and not yet paid.
  bool get approvedAhead =>
      approval != null && (approval!.status == 'scheduled' || approval!.status == 'paying');

  /// The owner may approve it now to be paid on its due date (as the web's
  /// ApproveAhead): not due yet, a saved PayPal email, PayPal planned, nothing
  /// blocking it, and not already approved.
  bool get canApproveAhead =>
      !dueNow && payeeEmail != null && plan != 'not_paypal' && blocks.isEmpty && !approvedAhead;

  /// Paid through PayPal on its due date: chosen, or not chosen and a
  /// PayPal email is saved (as the web's checkbox).
  bool get payWithPayPal => plan == 'paypal' || (plan == null && payeeEmail != null);
}

class BillPayPayee {
  const BillPayPayee({
    required this.contactId,
    this.name = '',
    this.paypalEmail = '',
    this.bank,
    this.confirmedAt,
  });

  factory BillPayPayee.fromJson(Map<String, dynamic> j) => BillPayPayee(
        contactId: _str(j['contact_id']),
        name: _str(j['name']),
        paypalEmail: _str(j['paypal_email']),
        bank: _strOrNull(j['bank']),
        confirmedAt: _strOrNull(j['confirmed_at']),
      );

  final String contactId;
  final String name;
  final String paypalEmail;
  final String? bank;
  final String? confirmedAt;
}

class BillPayFlag {
  const BillPayFlag({required this.id, this.supplier = '', this.reason = ''});

  factory BillPayFlag.fromJson(Map<String, dynamic> j) => BillPayFlag(
        id: _str(j['id']),
        supplier: _str(j['supplier']),
        reason: _str(j['reason']),
      );

  final String id;
  final String supplier;
  final String reason;
}

class BillPayNotice {
  const BillPayNotice({required this.id, this.text = '', this.kind = 'paid'});

  factory BillPayNotice.fromJson(Map<String, dynamic> j) => BillPayNotice(
        id: _str(j['id']),
        text: _str(j['text']),
        kind: _str(j['kind']).isEmpty ? 'paid' : _str(j['kind']),
      );

  final String id;
  final String text;

  /// paid | asked | flag | problem
  final String kind;

  bool get loud => kind == 'flag' || kind == 'problem';
}

class BillPayAutopilot {
  const BillPayAutopilot({
    this.enabled = false,
    this.suppliers = 0,
    this.changedAt,
    this.stoppedAt,
  });

  factory BillPayAutopilot.fromJson(Map<String, dynamic>? j) {
    if (j == null) return const BillPayAutopilot();
    final rules = _maps(j['rules']);
    return BillPayAutopilot(
      enabled: _bool(j['enabled']),
      suppliers: rules.where((r) => r['enabled'] != false).length,
      changedAt: _strOrNull(j['changed_at']),
      stoppedAt: _strOrNull(j['stopped_at']),
    );
  }

  final bool enabled;

  /// Suppliers with a rule switched on.
  final int suppliers;
  final String? changedAt;
  final String? stoppedAt;

  String get label => enabled ? 'On' : (stoppedAt != null ? 'Stopped' : 'Off');
}

/// `GET /billpay`.
class BillPayOverview {
  const BillPayOverview({
    this.today = '',
    this.available = false,
    this.reason,
    this.connected = false,
    this.testMode = false,
    this.clearingPence = 0,
    this.due = const [],
    this.upcoming = const [],
    this.payees = const [],
    this.payouts = const [],
    this.flags = const [],
    this.notices = const [],
    this.autopilot = const BillPayAutopilot(),
    this.autopilotNote = '',
  });

  factory BillPayOverview.fromJson(Map<String, dynamic> j) => BillPayOverview(
        today: _str(j['today']),
        available: _bool(j['available']),
        reason: _strOrNull(j['reason']),
        connected: _bool(j['connected']),
        testMode: _bool(j['test_mode']),
        clearingPence: _pence(j['clearing_pence']),
        due: [for (final m in _maps(j['due'])) BillPayBill.fromJson(m)],
        upcoming: [for (final m in _maps(j['upcoming'])) BillPayBill.fromJson(m)],
        payees: [for (final m in _maps(j['payees'])) BillPayPayee.fromJson(m)],
        payouts: [for (final m in _maps(j['payouts'])) BillPayout.fromJson(m)],
        flags: [for (final m in _maps(j['flags'])) BillPayFlag.fromJson(m)],
        notices: [for (final m in _maps(j['notices'])) BillPayNotice.fromJson(m)],
        autopilot: BillPayAutopilot.fromJson(_map(j['autopilot'])),
        autopilotNote: _str(j['autopilot_note']),
      );

  final String today;

  /// This server can send payouts.
  final bool available;
  final String? reason;

  /// PayPal linked to these books.
  final bool connected;

  /// PayPal sandbox: no real money moves.
  final bool testMode;

  /// 1240 PayPal clearing by the books.
  final int clearingPence;

  /// Due today or earlier, planned for PayPal.
  final List<BillPayBill> due;

  /// Every other open bill, soonest first.
  final List<BillPayBill> upcoming;
  final List<BillPayPayee> payees;
  final List<BillPayout> payouts;
  final List<BillPayFlag> flags;
  final List<BillPayNotice> notices;
  final BillPayAutopilot autopilot;
  final String autopilotNote;
}

/// `POST /billpay/run`: only the problems matter to the phone (what
/// Autopilot paid shows in the overview's notices and payouts).
class BillPayRunResult {
  const BillPayRunResult({this.paid = 0, this.problems = const []});

  factory BillPayRunResult.fromJson(Map<String, dynamic> j) => BillPayRunResult(
        paid: _maps(j['paid']).length,
        problems: _strings(j['problems']),
      );

  final int paid;
  final List<String> problems;
}

/// An approval in advance (`Approval`): the owner's yes to one payment,
/// paid the next time Accnomos is open on or after the due date, only if
/// nothing changed.
class BillPayApproval {
  const BillPayApproval({
    this.amountPence = 0,
    this.payeeEmail = '',
    this.dueDate = '',
    this.status = 'scheduled',
  });

  factory BillPayApproval.fromJson(Map<String, dynamic> j) => BillPayApproval(
        amountPence: _pence(j['amount_pence']),
        payeeEmail: _str(j['payee_email']),
        dueDate: _str(j['due_date']),
        status: _str(j['status']).isEmpty ? 'scheduled' : _str(j['status']),
      );

  final int amountPence;
  final String payeeEmail;
  final String dueDate;

  /// scheduled | paying | paid | cancelled | …
  final String status;
}

const upcomingStatusLabels = {
  'scheduled': 'Approved, waiting for its date',
  'planned': 'Needs your approval',
  'due_today': 'Due today',
  'paying': 'Paying',
  'paid': 'Paid',
  'needs_you': 'Needs you',
};

/// One upcoming PayPal bill payment (`UpcomingItem`).
class UpcomingPayment {
  const UpcomingPayment({
    required this.eventId,
    this.supplier = '',
    this.reference,
    this.date = '',
    this.amountPence = 0,
    this.payeeEmail,
    this.status = 'planned',
    this.approved = false,
    this.reason,
    this.inCalendar = false,
    this.calendarOutdated = false,
  });

  factory UpcomingPayment.fromJson(Map<String, dynamic> j) => UpcomingPayment(
        eventId: _str(j['event_id']),
        supplier: _str(j['supplier']),
        reference: _strOrNull(j['reference']),
        date: _str(j['date']),
        amountPence: _pence(j['amount_pence']),
        payeeEmail: _strOrNull(j['payee_email']),
        status: _str(j['status']).isEmpty ? 'planned' : _str(j['status']),
        approved: _bool(j['approved']),
        reason: _strOrNull(j['reason']),
        inCalendar: _bool(j['in_calendar']),
        calendarOutdated: _bool(j['calendar_outdated']),
      );

  final String eventId;
  final String supplier;
  final String? reference;

  /// The due date: paid the next time Accnomos is open on or after it.
  final String date;
  final int amountPence;
  final String? payeeEmail;

  /// scheduled | planned | due_today | paying | paid | needs_you
  final String status;

  /// Approved in advance (else planned).
  final bool approved;
  final String? reason;
  final bool inCalendar;
  final bool calendarOutdated;

  String get statusLabel => upcomingStatusLabels[status] ?? status;
  bool get settled => status == 'paid' || status == 'paying';
  bool get needsYou => status == 'needs_you';

  /// An approval in advance the owner can still cancel.
  bool get cancellable =>
      approved && (status == 'scheduled' || status == 'due_today' || status == 'needs_you');
}

/// `GET /billpay/upcoming`.
class UpcomingPayments {
  const UpcomingPayments({
    this.today = '',
    this.clearingPence = 0,
    this.clearingLabel = '1240 PayPal clearing by your books',
    this.next7Pence = 0,
    this.next30Pence = 0,
    this.warning,
    this.items = const [],
    this.calendarStale = const [],
    this.note = '',
  });

  factory UpcomingPayments.fromJson(Map<String, dynamic> j) => UpcomingPayments(
        today: _str(j['today']),
        clearingPence: _pence(j['clearing_pence']),
        clearingLabel: _str(j['clearing_label']).isEmpty
            ? '1240 PayPal clearing by your books'
            : _str(j['clearing_label']),
        next7Pence: _pence(j['next_7_pence']),
        next30Pence: _pence(j['next_30_pence']),
        warning: _strOrNull(j['warning']),
        items: [for (final m in _maps(j['items'])) UpcomingPayment.fromJson(m)],
        calendarStale: _strings(j['calendar_stale']),
        note: _str(j['note']),
      );

  final String today;
  final int clearingPence;
  final String clearingLabel;
  final int next7Pence;
  final int next30Pence;

  /// The shortfall warning against 1240 PayPal clearing.
  final String? warning;
  final List<UpcomingPayment> items;

  /// Bills whose calendar event is for a payment cancelled, paid or no
  /// longer planned.
  final List<String> calendarStale;
  final String note;

  List<UpcomingPayment> get open => [for (final i in items) if (!i.settled) i];
}

/// `POST /billpay/calendar` and `/billpay/calendar/remove`.
class CalendarSyncResult {
  const CalendarSyncResult({
    this.added = 0,
    this.updated = 0,
    this.unchanged = 0,
    this.removed = 0,
    this.notFound = 0,
  });

  factory CalendarSyncResult.fromJson(Map<String, dynamic> j) => CalendarSyncResult(
        added: _pence(j['added']),
        updated: _pence(j['updated']),
        unchanged: _pence(j['unchanged']),
        removed: _pence(j['removed']),
        notFound: _pence(j['not_found']),
      );

  final int added;
  final int updated;
  final int unchanged;
  final int removed;
  final int notFound;

  /// "1 added, 2 already there" or "nothing to add".
  String get addedSummary {
    final parts = [
      if (added > 0) '$added added',
      if (updated > 0) '$updated updated',
      if (unchanged > 0) '$unchanged already there',
    ];
    return parts.isEmpty ? 'nothing to add' : parts.join(', ');
  }
}
