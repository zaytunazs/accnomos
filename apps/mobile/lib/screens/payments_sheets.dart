import 'package:flutter/material.dart';

import '../services/books.dart';
import '../theme.dart';

/// Bottom sheets for payments, credit notes and credits.
///
/// Mirrors the web dialogs in `apps/web/src/components/invoices/`:
/// `PaymentDialogs.tsx` (record/remove payment, void rule) and
/// `CreditDialogs.tsx` (credit notes, apply/refund credit, bill payments).
/// Thin client only: every figure shown comes from the runtime (or is what
/// the user just typed); Dart only formats for display. Each action asks
/// first in a confirmation sheet, shows the runtime's refusal sentence when
/// it says no, and hands the runtime's answer back so the caller refreshes.

/// `£12.34` (or `12.34`, with commas/spaces tolerated) to integer pence.
/// Null when it is not a plain pounds amount with at most two decimals.
int? parsePoundsToPence(String text) {
  final cleaned = text
      .trim()
      .replaceAll('£', '')
      .replaceAll(',', '')
      .replaceAll(' ', '');
  final match = RegExp(r'^(\d+)(?:\.(\d{1,2}))?$').firstMatch(cleaned);
  if (match == null) return null;
  final pence = (match.group(2) ?? '').padRight(2, '0');
  final total = int.parse(match.group(1)!) * 100 + int.parse(pence);
  return total <= 0 ? null : total;
}

/// Pence back to a `£`-less input value, e.g. 1234 → `12.34`.
String poundsInput(num pence) => (pence / 100).toStringAsFixed(2);

/// Today as `YYYY-MM-DD` on the phone, for runtime date fields.
String todayIso() => isoDate(DateTime.now());

/// One figure row in a confirmation sheet: a label and the runtime's (or
/// the user's) text, never computed here.
class ConfirmFigure {
  const ConfirmFigure(this.label, this.value);
  final String label;
  final String value;
}

/// "Are you sure?" with the figures, then the runtime call. Returns true
/// when [action] succeeded; shows the runtime's refusal sentence inside the
/// sheet otherwise (the sheet stays open so the user can read it).
Future<bool> showConfirmSheet({
  required BuildContext context,
  required String title,
  required List<ConfirmFigure> figures,
  required String confirmLabel,
  required Future<void> Function() action,
}) async {
  final done = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.white,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (_) => _ConfirmSheet(
      title: title,
      figures: figures,
      confirmLabel: confirmLabel,
      action: action,
    ),
  );
  return done ?? false;
}

class _ConfirmSheet extends StatefulWidget {
  const _ConfirmSheet({
    required this.title,
    required this.figures,
    required this.confirmLabel,
    required this.action,
  });

  final String title;
  final List<ConfirmFigure> figures;
  final String confirmLabel;
  final Future<void> Function() action;

  @override
  State<_ConfirmSheet> createState() => _ConfirmSheetState();
}

class _ConfirmSheetState extends State<_ConfirmSheet> {
  bool _busy = false;
  String? _error;

  Future<void> _confirm() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.action();
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SingleChildScrollView(
        padding: EdgeInsets.fromLTRB(
          20,
          12,
          20,
          20 + MediaQuery.of(context).viewInsets.bottom,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: const Color(0xFFE3E1D8),
                  borderRadius: BorderRadius.circular(999),
                ),
              ),
            ),
            const SizedBox(height: 12),
            Text(
              widget.title,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 12),
            for (final figure in widget.figures) ...[
              _figureRow(figure.label, figure.value),
              const SizedBox(height: 6),
            ],
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(
                _error!,
                style: const TextStyle(
                  color: Color(0xFF8A3F06),
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(52),
                    ),
                    onPressed:
                        _busy ? null : () => Navigator.of(context).pop(false),
                    child: const Text('Back'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FilledButton(
                    style: FilledButton.styleFrom(
                      backgroundColor: AccnomosColors.teal,
                      minimumSize: const Size.fromHeight(52),
                    ),
                    onPressed: _busy ? null : _confirm,
                    child: Text(_busy ? 'Saving…' : widget.confirmLabel),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _figureRow(String label, String value) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Text(
            label,
            style: const TextStyle(color: AccnomosColors.muted),
          ),
        ),
        const SizedBox(width: 12),
        Flexible(
          child: Text(
            value,
            textAlign: TextAlign.right,
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
        ),
      ],
    );
  }
}

/// Shared text-field decoration for the payment sheets.
InputDecoration sheetField(String label, {String? hint, String? error}) {
  return InputDecoration(
    labelText: label,
    hintText: hint,
    errorText: error,
    border: const OutlineInputBorder(),
    filled: true,
    fillColor: Colors.white,
  );
}

/// Account picker: 1200 Bank or 1210 Cash, like the web dialogs.
class AccountPicker extends StatelessWidget {
  const AccountPicker({
    super.key,
    required this.value,
    required this.onChanged,
  });

  final String value;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return DropdownButtonFormField<String>(
      initialValue: value,
      decoration: sheetField('Account'),
      items: const [
        DropdownMenuItem(
          value: '1200 Bank',
          child: Text('Bank'),
        ),
        DropdownMenuItem(
          value: '1210 Cash',
          child: Text('Cash'),
        ),
      ],
      onChanged: (next) {
        if (next != null) onChanged(next);
      },
    );
  }
}

/// Record a payment on a sales invoice (`POST /invoices/{number}/payments`).
/// [balancePence] is the runtime's balance and pre-fills the amount; more
/// than the balance stays as a credit on the customer. Returns the runtime's
/// updated invoice when it records, null when cancelled.
Future<Map<String, dynamic>?> showRecordPaymentSheet({
  required BuildContext context,
  required String invoiceNumber,
  required num balancePence,
  required Future<Map<String, dynamic>> Function({
    required int amountPence,
    required String paidOn,
    required String account,
    String? paymentRef,
  }) record,
}) async {
  return showModalBottomSheet<Map<String, dynamic>>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.white,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (_) => _RecordPaymentSheet(
      invoiceNumber: invoiceNumber,
      balancePence: balancePence,
      record: record,
    ),
  );
}

class _RecordPaymentSheet extends StatefulWidget {
  const _RecordPaymentSheet({
    required this.invoiceNumber,
    required this.balancePence,
    required this.record,
  });

  final String invoiceNumber;
  final num balancePence;
  final Future<Map<String, dynamic>> Function({
    required int amountPence,
    required String paidOn,
    required String account,
    String? paymentRef,
  }) record;

  @override
  State<_RecordPaymentSheet> createState() => _RecordPaymentSheetState();
}

class _RecordPaymentSheetState extends State<_RecordPaymentSheet> {
  late final TextEditingController _amount;
  late final TextEditingController _date;
  final _reference = TextEditingController();
  String _account = '1200 Bank';
  String? _amountError;

  @override
  void initState() {
    super.initState();
    _amount = TextEditingController(text: poundsInput(widget.balancePence));
    _date = TextEditingController(text: todayIso());
  }

  @override
  void dispose() {
    _amount.dispose();
    _date.dispose();
    _reference.dispose();
    super.dispose();
  }

  Future<void> _continue() async {
    final pence = parsePoundsToPence(_amount.text);
    if (pence == null) {
      setState(() => _amountError = 'Enter an amount in pounds, e.g. 120.50.');
      return;
    }
    final day = _date.text.trim();
    if (!RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(day)) {
      setState(() => _amountError = null);
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Use a date like 2026-10-27.')));
      return;
    }
    setState(() => _amountError = null);
    final amount = gbp(pence);
    final reference =
        _reference.text.trim().isEmpty ? null : _reference.text.trim();
    Map<String, dynamic>? recorded;
    final confirmed = await showConfirmSheet(
      // ignore: use_build_context_synchronously
      context: context,
      title: 'Record payment on ${widget.invoiceNumber}?',
      figures: [
        ConfirmFigure('Amount', amount),
        ConfirmFigure('Date', ukDate(day)),
        ConfirmFigure(
            'Account', _account == '1210 Cash' ? 'Cash' : 'Bank'),
        if (reference != null) ConfirmFigure('Reference', reference),
        ConfirmFigure('Balance owed', gbp(widget.balancePence)),
      ],
      confirmLabel: 'Record payment',
      action: () async {
        recorded = await widget.record(
          amountPence: pence,
          paidOn: day,
          account: _account,
          paymentRef: reference,
        );
      },
    );
    if (confirmed && mounted) {
      // ignore: use_build_context_synchronously
      Navigator.of(context).pop(recorded);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SingleChildScrollView(
        padding: EdgeInsets.fromLTRB(
          20,
          12,
          20,
          20 + MediaQuery.of(context).viewInsets.bottom,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Record payment on ${widget.invoiceNumber}',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 4),
            Text(
              'Balance owed: ${gbp(widget.balancePence)}.',
              style: const TextStyle(color: AccnomosColors.muted),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _amount,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: sheetField('Amount (£)',
                  hint: 'e.g. 120.50', error: _amountError),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _date,
              keyboardType: TextInputType.datetime,
              decoration: sheetField('Date', hint: 'YYYY-MM-DD'),
            ),
            const SizedBox(height: 12),
            AccountPicker(
              value: _account,
              onChanged: (next) => setState(() => _account = next),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _reference,
              decoration: sheetField('Reference (optional)',
                  hint: 'e.g. bank transfer ref'),
            ),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size.fromHeight(52),
                ),
                onPressed: _continue,
                child: const Text('Continue'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Create a credit note for a sent invoice
/// (`POST /invoices/{number}/credit-notes`): the whole invoice or chosen
/// lines and quantities. Returns the created credit note (carrying its
/// number, e.g. CN-0001) when posted, null when cancelled.
Future<Map<String, dynamic>?> showCreateCreditNoteSheet({
  required BuildContext context,
  required String invoiceNumber,
  required List<Map<String, dynamic>> lines,
  required Future<Map<String, dynamic>> Function({
    required String reason,
    String? issueDate,
    List<Map<String, String>>? creditLines,
  }) create,
}) async {
  return showModalBottomSheet<Map<String, dynamic>>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.white,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (_) => _CreateCreditNoteSheet(
      invoiceNumber: invoiceNumber,
      lines: lines,
      create: create,
    ),
  );
}

class _CreateCreditNoteSheet extends StatefulWidget {
  const _CreateCreditNoteSheet({
    required this.invoiceNumber,
    required this.lines,
    required this.create,
  });

  final String invoiceNumber;
  final List<Map<String, dynamic>> lines;
  final Future<Map<String, dynamic>> Function({
    required String reason,
    String? issueDate,
    List<Map<String, String>>? creditLines,
  }) create;

  @override
  State<_CreateCreditNoteSheet> createState() => _CreateCreditNoteSheetState();
}

class _CreateCreditNoteSheetState extends State<_CreateCreditNoteSheet> {
  bool _whole = true;
  late final List<bool> _picked;
  late final List<TextEditingController> _quantities;
  final _reason = TextEditingController();
  late final TextEditingController _date;
  String? _error;

  @override
  void initState() {
    super.initState();
    _picked = List<bool>.filled(widget.lines.length, true);
    _quantities = [
      for (final line in widget.lines)
        TextEditingController(
            text: (line['quantity'] ?? '1').toString()),
    ];
    _date = TextEditingController(text: todayIso());
  }

  @override
  void dispose() {
    for (final controller in _quantities) {
      controller.dispose();
    }
    _reason.dispose();
    _date.dispose();
    super.dispose();
  }

  Future<void> _continue() async {
    final reason = _reason.text.trim();
    if (reason.isEmpty) {
      setState(() => _error = 'Say why this credit note is raised.');
      return;
    }
    final day = _date.text.trim();
    if (!RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(day)) {
      setState(() => _error = 'Use a date like 2026-10-27.');
      return;
    }
    List<Map<String, String>>? creditLines;
    if (!_whole) {
      creditLines = [];
      for (var i = 0; i < widget.lines.length; i++) {
        if (_picked[i]) {
          final quantity = _quantities[i].text.trim();
          if (quantity.isEmpty) {
            setState(
                () => _error = 'Each picked line needs a quantity.');
            return;
          }
          creditLines.add({'line': '${i + 1}', 'quantity': quantity});
        }
      }
      if (creditLines.isEmpty) {
        setState(() => _error = 'Pick at least one line, or credit all.');
        return;
      }
    }
    setState(() => _error = null);
    final scope =
        _whole ? 'the whole invoice' : '${creditLines!.length} line(s)';
    final linesForCall = creditLines;
    Map<String, dynamic>? created;
    final confirmed = await showConfirmSheet(
      // ignore: use_build_context_synchronously
      context: context,
      title: 'Create credit note for ${widget.invoiceNumber}?',
      figures: [
        ConfirmFigure('Credits', scope),
        ConfirmFigure('Date', ukDate(day)),
        ConfirmFigure('Reason', reason),
      ],
      confirmLabel: 'Create credit note',
      action: () async {
        created = await widget.create(
          reason: reason,
          issueDate: day,
          creditLines: linesForCall,
        );
      },
    );
    if (confirmed && mounted) {
      // ignore: use_build_context_synchronously
      Navigator.of(context).pop(created);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SingleChildScrollView(
        padding: EdgeInsets.fromLTRB(
          20,
          12,
          20,
          20 + MediaQuery.of(context).viewInsets.bottom,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Create credit note',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 4),
            Text(
              'For ${widget.invoiceNumber}. Posted at once.',
              style: const TextStyle(color: AccnomosColors.muted),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: ChoiceChip(
                    label: const Text('Whole invoice'),
                    selected: _whole,
                    onSelected: (_) => setState(() => _whole = true),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: ChoiceChip(
                    label: const Text('Chosen lines'),
                    selected: !_whole,
                    onSelected: (_) => setState(() => _whole = false),
                  ),
                ),
              ],
            ),
            if (!_whole) ...[
              const SizedBox(height: 8),
              for (var i = 0; i < widget.lines.length; i++)
                _creditLineRow(i),
            ],
            const SizedBox(height: 12),
            TextField(
              controller: _reason,
              decoration: sheetField('Reason',
                  hint: 'e.g. returned goods, overcharge'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _date,
              keyboardType: TextInputType.datetime,
              decoration: sheetField('Date', hint: 'YYYY-MM-DD'),
            ),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(
                _error!,
                style: const TextStyle(
                  color: Color(0xFF8A3F06),
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size.fromHeight(52),
                ),
                onPressed: _continue,
                child: const Text('Continue'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _creditLineRow(int i) {
    final line = widget.lines[i];
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        children: [
          Checkbox(
            value: _picked[i],
            onChanged: (next) =>
                setState(() => _picked[i] = next ?? false),
          ),
          Expanded(
            child: Text(
              (line['description'] ?? 'Line ${i + 1}').toString(),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            width: 72,
            child: TextField(
              controller: _quantities[i],
              keyboardType: TextInputType.number,
              decoration: sheetField('Qty'),
            ),
          ),
        ],
      ),
    );
  }
}

/// One-line summary of a credit on account (a runtime `Credit` row): amount
/// plus where it came from. Display only.
String creditLabel(Map<String, dynamic> credit) {
  final amount = gbp((credit['amount_pence'] ?? 0) as num);
  final source =
      (credit['source'] ?? '').toString() == 'payment' ? 'overpayment' : 'credit note';
  final reference = (credit['reference'] ?? '').toString();
  final date = ukDate((credit['date'] ?? '').toString());
  return '$amount from $source${reference.isNotEmpty ? ' ($reference)' : ''} · $date';
}

/// One-line summary of an open invoice/bill (a runtime `open_documents`
/// row). Display only.
String openDocLabel(Map<String, dynamic> doc) {
  final reference = (doc['reference'] ?? '').toString();
  final name = (doc['counterparty'] ?? '').toString();
  final what = reference.isNotEmpty ? reference : name;
  final left = gbp((doc['outstanding_pence'] ?? 0) as num);
  final date = ukDate((doc['date'] ?? '').toString());
  return '$what · $date · $left left';
}

/// Apply a credit on account towards another open invoice/bill of the same
/// contact (`POST /credits/apply`). Nothing is posted: the money is already
/// on the contact's side. The amount is left blank for "as much as both
/// allow" unless the user types less (both figures shown come from the
/// runtime). Returns the runtime's `CreditUse` when applied.
Future<Map<String, dynamic>?> showApplyCreditSheet({
  required BuildContext context,
  required String contactName,
  required List<Map<String, dynamic>> credits,
  required List<Map<String, dynamic>> documents,
  required Future<Map<String, dynamic>> Function({
    required String credit,
    required String eventId,
    int? amountPence,
    String? date,
  }) apply,
}) async {
  return showModalBottomSheet<Map<String, dynamic>>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.white,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (_) => _ApplyCreditSheet(
      contactName: contactName,
      credits: credits,
      documents: documents,
      apply: apply,
    ),
  );
}

class _ApplyCreditSheet extends StatefulWidget {
  const _ApplyCreditSheet({
    required this.contactName,
    required this.credits,
    required this.documents,
    required this.apply,
  });

  final String contactName;
  final List<Map<String, dynamic>> credits;
  final List<Map<String, dynamic>> documents;
  final Future<Map<String, dynamic>> Function({
    required String credit,
    required String eventId,
    int? amountPence,
    String? date,
  }) apply;

  @override
  State<_ApplyCreditSheet> createState() => _ApplyCreditSheetState();
}

class _ApplyCreditSheetState extends State<_ApplyCreditSheet> {
  late String _creditId;
  String? _docId;
  final _amount = TextEditingController();
  late final TextEditingController _date;
  String? _error;

  @override
  void initState() {
    super.initState();
    _creditId = widget.credits.first['id'].toString();
    _date = TextEditingController(text: todayIso());
  }

  @override
  void dispose() {
    _amount.dispose();
    _date.dispose();
    super.dispose();
  }

  Map<String, dynamic>? get _credit {
    for (final credit in widget.credits) {
      if (credit['id'].toString() == _creditId) return credit;
    }
    return null;
  }

  List<Map<String, dynamic>> get _docs {
    final credit = _credit;
    if (credit == null) return const [];
    final side = (credit['side'] ?? '').toString();
    return [
      for (final doc in widget.documents)
        if ((doc['side'] ?? '').toString() == side &&
            ((doc['outstanding_pence'] ?? 0) as num) > 0)
          doc,
    ];
  }

  Future<void> _continue() async {
    final credit = _credit;
    if (credit == null) return;
    final docId = _docId;
    if (docId == null || docId.isEmpty) {
      setState(() => _error = 'Choose an invoice or bill to apply to.');
      return;
    }
    final typed = _amount.text.trim();
    int? pence;
    if (typed.isNotEmpty) {
      pence = parsePoundsToPence(typed);
      if (pence == null) {
        setState(
            () => _error = 'Enter an amount in pounds, e.g. 120.50.');
        return;
      }
    }
    final day = _date.text.trim();
    if (!RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(day)) {
      setState(() => _error = 'Use a date like 2026-10-27.');
      return;
    }
    setState(() => _error = null);
    final creditId = _creditId;
    final amountForCall = pence;
    Map<String, dynamic>? used;
    final confirmed = await showConfirmSheet(
      // ignore: use_build_context_synchronously
      context: context,
      title: 'Apply credit for ${widget.contactName}?',
      figures: [
        ConfirmFigure('Credit', creditLabel(credit)),
        ConfirmFigure(
            'To',
            openDocLabel(widget.documents.firstWhere(
                (doc) => doc['event_id'].toString() == docId))),
        ConfirmFigure('Amount',
            amountForCall == null ? 'As much as both allow' : gbp(amountForCall)),
        ConfirmFigure('Date', ukDate(day)),
      ],
      confirmLabel: 'Apply credit',
      action: () async {
        used = await widget.apply(
          credit: creditId,
          eventId: docId,
          amountPence: amountForCall,
          date: day,
        );
      },
    );
    if (confirmed && mounted) {
      // ignore: use_build_context_synchronously
      Navigator.of(context).pop(used);
    }
  }

  @override
  Widget build(BuildContext context) {
    final docs = _docs;
    return SafeArea(
      child: SingleChildScrollView(
        padding: EdgeInsets.fromLTRB(
          20,
          12,
          20,
          20 + MediaQuery.of(context).viewInsets.bottom,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Apply credit for ${widget.contactName}',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 4),
            const Text(
              'Money already on their account goes towards another of their documents. Nothing new is posted.',
              style: TextStyle(color: AccnomosColors.muted),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _creditId,
              decoration: sheetField('Credit'),
              items: [
                for (final credit in widget.credits)
                  DropdownMenuItem(
                    value: credit['id'].toString(),
                    child: Text(
                      creditLabel(credit),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
              ],
              onChanged: (next) {
                if (next == null) return;
                setState(() {
                  _creditId = next;
                  _docId = null;
                });
              },
            ),
            const SizedBox(height: 12),
            if (docs.isEmpty)
              const Text(
                'Nothing of theirs is waiting to be paid. Refund the credit instead.',
                style: TextStyle(color: AccnomosColors.muted),
              )
            else
              DropdownButtonFormField<String>(
                initialValue: _docId,
                decoration: sheetField('Invoice or bill'),
                items: [
                  for (final doc in docs)
                    DropdownMenuItem(
                      value: doc['event_id'].toString(),
                      child: Text(
                        openDocLabel(doc),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                ],
                onChanged: (next) => setState(() => _docId = next),
              ),
            const SizedBox(height: 12),
            TextField(
              controller: _amount,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: sheetField('Amount (£, optional)',
                  hint: 'Blank for as much as both allow'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _date,
              keyboardType: TextInputType.datetime,
              decoration: sheetField('Date', hint: 'YYYY-MM-DD'),
            ),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(
                _error!,
                style: const TextStyle(
                  color: Color(0xFF8A3F06),
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size.fromHeight(52),
                ),
                onPressed: docs.isEmpty ? null : _continue,
                child: const Text('Continue'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Refund a credit on account (`POST /credits/refund`): pay a customer's
/// credit back, or record a supplier paying theirs back. Posted by the
/// runtime. Returns the runtime's `CreditUse` when recorded.
Future<Map<String, dynamic>?> showRefundSheet({
  required BuildContext context,
  required String contactName,
  required List<Map<String, dynamic>> credits,
  required Future<Map<String, dynamic>> Function({
    required String credit,
    required int amountPence,
    required String date,
    required String account,
    String? reference,
  }) refund,
}) async {
  return showModalBottomSheet<Map<String, dynamic>>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.white,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (_) => _RefundSheet(
      contactName: contactName,
      credits: credits,
      refund: refund,
    ),
  );
}

class _RefundSheet extends StatefulWidget {
  const _RefundSheet({
    required this.contactName,
    required this.credits,
    required this.refund,
  });

  final String contactName;
  final List<Map<String, dynamic>> credits;
  final Future<Map<String, dynamic>> Function({
    required String credit,
    required int amountPence,
    required String date,
    required String account,
    String? reference,
  }) refund;

  @override
  State<_RefundSheet> createState() => _RefundSheetState();
}

class _RefundSheetState extends State<_RefundSheet> {
  late String _creditId;
  late final TextEditingController _amount;
  late final TextEditingController _date;
  final _reference = TextEditingController();
  String _account = '1200 Bank';
  String? _error;

  @override
  void initState() {
    super.initState();
    _creditId = widget.credits.first['id'].toString();
    _amount = TextEditingController(
        text: poundsInput(
            (widget.credits.first['amount_pence'] ?? 0) as num));
    _date = TextEditingController(text: todayIso());
  }

  @override
  void dispose() {
    _amount.dispose();
    _date.dispose();
    _reference.dispose();
    super.dispose();
  }

  Map<String, dynamic>? get _credit {
    for (final credit in widget.credits) {
      if (credit['id'].toString() == _creditId) return credit;
    }
    return null;
  }

  Future<void> _continue() async {
    final credit = _credit;
    if (credit == null) return;
    final pence = parsePoundsToPence(_amount.text);
    if (pence == null) {
      setState(() => _error = 'Enter an amount in pounds, e.g. 120.50.');
      return;
    }
    final day = _date.text.trim();
    if (!RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(day)) {
      setState(() => _error = 'Use a date like 2026-10-27.');
      return;
    }
    setState(() => _error = null);
    final reference =
        _reference.text.trim().isEmpty ? null : _reference.text.trim();
    final creditId = _creditId;
    final account = _account;
    Map<String, dynamic>? used;
    final confirmed = await showConfirmSheet(
      // ignore: use_build_context_synchronously
      context: context,
      title: 'Refund credit for ${widget.contactName}?',
      figures: [
        ConfirmFigure('Refund', gbp(pence)),
        ConfirmFigure('Date', ukDate(day)),
        ConfirmFigure(
            'Account', account == '1210 Cash' ? 'Cash' : 'Bank'),
        if (reference != null) ConfirmFigure('Reference', reference),
        ConfirmFigure('Credit on account', creditLabel(credit)),
      ],
      confirmLabel: 'Refund',
      action: () async {
        used = await widget.refund(
          credit: creditId,
          amountPence: pence,
          date: day,
          account: account,
          reference: reference,
        );
      },
    );
    if (confirmed && mounted) {
      // ignore: use_build_context_synchronously
      Navigator.of(context).pop(used);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SingleChildScrollView(
        padding: EdgeInsets.fromLTRB(
          20,
          12,
          20,
          20 + MediaQuery.of(context).viewInsets.bottom,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Refund credit for ${widget.contactName}',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 4),
            const Text(
              'Paid back from your books and posted by the runtime.',
              style: TextStyle(color: AccnomosColors.muted),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _creditId,
              decoration: sheetField('Credit'),
              items: [
                for (final credit in widget.credits)
                  DropdownMenuItem(
                    value: credit['id'].toString(),
                    child: Text(
                      creditLabel(credit),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
              ],
              onChanged: (next) {
                if (next == null) return;
                setState(() {
                  _creditId = next;
                  final picked = _credit;
                  if (picked != null) {
                    _amount.text =
                        poundsInput((picked['amount_pence'] ?? 0) as num);
                  }
                });
              },
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _amount,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: sheetField('Amount (£)'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _date,
              keyboardType: TextInputType.datetime,
              decoration: sheetField('Date', hint: 'YYYY-MM-DD'),
            ),
            const SizedBox(height: 12),
            AccountPicker(
              value: _account,
              onChanged: (next) => setState(() => _account = next),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _reference,
              decoration: sheetField('Reference (optional)'),
            ),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(
                _error!,
                style: const TextStyle(
                  color: Color(0xFF8A3F06),
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size.fromHeight(52),
                ),
                onPressed: _continue,
                child: const Text('Continue'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Record a payment on one bill (`POST /payments`, side `purchase`:
/// Dr 2100 Creditors / Cr 1200 Bank). [openDoc] is the runtime's
/// `open_documents` row; its outstanding pre-fills the amount and money over
/// stays as a credit the supplier owes. Returns the runtime's
/// `PaymentRecord` when recorded.
Future<Map<String, dynamic>?> showRecordBillPaymentSheet({
  required BuildContext context,
  required Map<String, dynamic> openDoc,
  required Future<Map<String, dynamic>> Function(
      Map<String, dynamic> body) record,
}) async {
  return showModalBottomSheet<Map<String, dynamic>>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.white,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (_) => _RecordBillPaymentSheet(
      openDoc: openDoc,
      record: record,
    ),
  );
}

class _RecordBillPaymentSheet extends StatefulWidget {
  const _RecordBillPaymentSheet({
    required this.openDoc,
    required this.record,
  });

  final Map<String, dynamic> openDoc;
  final Future<Map<String, dynamic>> Function(Map<String, dynamic> body) record;

  @override
  State<_RecordBillPaymentSheet> createState() =>
      _RecordBillPaymentSheetState();
}

class _RecordBillPaymentSheetState extends State<_RecordBillPaymentSheet> {
  late final TextEditingController _amount;
  late final TextEditingController _date;
  final _reference = TextEditingController();
  String _account = '1200 Bank';
  String? _error;

  @override
  void initState() {
    super.initState();
    _amount = TextEditingController(
        text: poundsInput((widget.openDoc['outstanding_pence'] ?? 0) as num));
    _date = TextEditingController(text: todayIso());
  }

  @override
  void dispose() {
    _amount.dispose();
    _date.dispose();
    _reference.dispose();
    super.dispose();
  }

  Future<void> _continue() async {
    final pence = parsePoundsToPence(_amount.text);
    if (pence == null) {
      setState(() => _error = 'Enter an amount in pounds, e.g. 120.50.');
      return;
    }
    final day = _date.text.trim();
    if (!RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(day)) {
      setState(() => _error = 'Use a date like 2026-10-27.');
      return;
    }
    setState(() => _error = null);
    final reference =
        _reference.text.trim().isEmpty ? null : _reference.text.trim();
    final body = <String, dynamic>{
      'side': 'purchase',
      'date': day,
      'amount_pence': pence,
      'account': _account,
      'reference': ?reference,
      'allocations': [
        {
          'event_id': widget.openDoc['event_id'].toString(),
          'amount_pence': pence,
        },
      ],
    };
    Map<String, dynamic>? recorded;
    final confirmed = await showConfirmSheet(
      // ignore: use_build_context_synchronously
      context: context,
      title: 'Pay ${(widget.openDoc['reference'] ?? 'the bill').toString()}?',
      figures: [
        ConfirmFigure('Amount', gbp(pence)),
        ConfirmFigure('Date', ukDate(day)),
        ConfirmFigure(
            'Account', _account == '1210 Cash' ? 'Cash' : 'Bank'),
        if (reference != null) ConfirmFigure('Reference', reference),
        ConfirmFigure('Still owed on the bill',
            gbp((widget.openDoc['outstanding_pence'] ?? 0) as num)),
      ],
      confirmLabel: 'Record payment',
      action: () async {
        recorded = await widget.record(body);
      },
    );
    if (confirmed && mounted) {
      // ignore: use_build_context_synchronously
      Navigator.of(context).pop(recorded);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SingleChildScrollView(
        padding: EdgeInsets.fromLTRB(
          20,
          12,
          20,
          20 + MediaQuery.of(context).viewInsets.bottom,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Pay ${(widget.openDoc['reference'] ?? 'the bill').toString()}',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 4),
            Text(
              'Still owed: ${gbp((widget.openDoc['outstanding_pence'] ?? 0) as num)}.',
              style: const TextStyle(color: AccnomosColors.muted),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _amount,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: sheetField('Amount (£)',
                  hint: 'e.g. 120.50', error: _error),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _date,
              keyboardType: TextInputType.datetime,
              decoration: sheetField('Date', hint: 'YYYY-MM-DD'),
            ),
            const SizedBox(height: 12),
            AccountPicker(
              value: _account,
              onChanged: (next) => setState(() => _account = next),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _reference,
              decoration: sheetField('Reference (optional)'),
            ),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size.fromHeight(52),
                ),
                onPressed: _continue,
                child: const Text('Continue'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
