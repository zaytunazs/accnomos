import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models/proposal.dart';
import '../services/proposal_editing.dart';
import '../theme.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);

/// Result of the edit sheet: the `edits` map for `POST .../approve`
/// (only changed runtime fields) plus a locally corrected proposal for
/// the signed-out preview. The VAT code and the VAT number are validated
/// here but never sent — the runtime keeps them as read.
class EditResult {
  EditResult({required this.edits, required this.updated});
  final Map<String, dynamic> edits;
  final Proposal updated;
}

/// Edit-sheet field → the verifier's field key
/// (`services/runtime/app/ai/verify.py`, like the web's VERIFIER_FIELD).
const _verifierField = {
  'supplier': 'supplier_name',
  'vrn': 'supplier_vat_number',
  'date': 'date',
  'net': 'net_total',
  'vat': 'vat_total',
  'gross': 'gross_total',
};

/// Bottom sheet to correct a proposal before approving it.
class EditProposalSheet extends StatefulWidget {
  const EditProposalSheet({super.key, required this.proposal});
  final Proposal proposal;

  @override
  State<EditProposalSheet> createState() => _EditProposalSheetState();
}

class _EditProposalSheetState extends State<EditProposalSheet> {
  late final TextEditingController _supplier;
  late final TextEditingController _net;
  late final TextEditingController _vat;
  late final TextEditingController _gross;
  late final TextEditingController _vrn;

  late final String? _initialDateIso;
  late String? _dateIso;
  bool _dateTouched = false;

  late final String? _initialVrn;
  late String _vatCode;
  late String _category;

  @override
  void initState() {
    super.initState();
    final proposal = widget.proposal;
    _supplier = TextEditingController(text: proposal.supplier);
    _net = TextEditingController(
        text: proposal.net == null ? '' : proposal.net!.toStringAsFixed(2));
    _vat = TextEditingController(
        text: proposal.vat == null ? '' : proposal.vat!.toStringAsFixed(2));
    _gross = TextEditingController(text: proposal.total.toStringAsFixed(2));
    _vrn = TextEditingController(text: proposal.supplierVrn ?? '');
    _initialVrn = proposal.supplierVrn;
    final parsed = tryParseProposalDate(proposal.date);
    _initialDateIso = parsed == null ? null : formatIsoDate(parsed);
    _dateIso = _initialDateIso ?? formatIsoDate(DateTime.now());
    final netPence = parsePoundsToPence(_net.text) ?? 0;
    final vatPence = parsePoundsToPence(_vat.text) ?? 0;
    _vatCode = inferVatCode(netPence: netPence, vatPence: vatPence);
    _category =
        kCategories.contains(proposal.category) ? proposal.category : 'Sundry';
  }

  @override
  void dispose() {
    _supplier.dispose();
    _net.dispose();
    _vat.dispose();
    _gross.dispose();
    _vrn.dispose();
    super.dispose();
  }

  int? get _netPence => parsePoundsToPence(_net.text);
  int? get _vatPence => parsePoundsToPence(_vat.text);
  int? get _grossPence => parsePoundsToPence(_gross.text);

  /// Every reason the sheet cannot be saved yet, first problem first.
  List<EditFieldProblem> get _problems => validateEditForm(
        supplier: _supplier.text,
        dateIso: _dateIso ?? '',
        netText: _net.text,
        vatText: _vat.text,
        grossText: _gross.text,
        category: _category,
        vrnText: _vrn.text,
        initialVrn: _initialVrn,
        vatCode: _vatCode,
        linesCount: widget.proposal.lineCount,
      );

  EditFieldProblem? _problemFor(String field) {
    for (final problem in _problems) {
      if (problem.field == field) return problem;
    }
    return null;
  }

  /// The second reading of this field when it disagreed with the first.
  String? _disagreed(String field) {
    final key = _verifierField[field];
    if (key == null) return null;
    for (final diff in widget.proposal.verifierDiffs) {
      if (diff.key == key) return diff.verifier;
    }
    return null;
  }

  void _pickDate() async {
    final initial =
        tryParseProposalDate(_dateIso ?? '') ?? DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: DateTime(2000),
      lastDate: DateTime.now().add(const Duration(days: 365)),
    );
    if (picked == null || !mounted) return;
    setState(() {
      _dateIso = formatIsoDate(picked);
      _dateTouched = true;
    });
  }

  void _save() {
    if (_problems.isNotEmpty) return;
    final proposal = widget.proposal;
    final net = _netPence! / 100.0;
    final vat = _vatPence! / 100.0;
    final gross = _grossPence! / 100.0;
    final display =
        formatDisplayDate(tryParseProposalDate(_dateIso!) ?? DateTime.now());
    final edits = buildEdits(
      initialSupplier: proposal.supplier,
      currentSupplier: _supplier.text,
      initialDateIso: _initialDateIso,
      currentDateIso: _dateIso,
      dateTouched: _dateTouched,
      initialNet: proposal.net,
      currentNet: net,
      initialVat: proposal.vat,
      currentVat: vat,
      initialGross: proposal.total,
      currentGross: gross,
      initialCategory: proposal.category,
      currentCategory: _category,
    );
    Navigator.of(context).pop(EditResult(
      edits: edits,
      updated: proposal.copyWith(
        supplier: _supplier.text.trim(),
        total: gross,
        date: display,
        category: _category,
        net: net,
        vat: vat,
      ),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final problems = _problems;
    final dateLabel = formatDisplayDate(
        tryParseProposalDate(_dateIso ?? '') ?? DateTime.now());
    final dateProblem = _problemFor('date');
    final dateSecond = _disagreed('date');
    final status = problems.isEmpty
        ? null
        : "Can't save yet: ${problems.first.message}"
            '${problems.length > 1 ? ' (and ${problems.length - 1} more)' : ''}';
    return SafeArea(
      child: SingleChildScrollView(
        padding: EdgeInsets.only(
          left: 20,
          right: 20,
          top: 12,
          bottom: 20 + MediaQuery.of(context).viewInsets.bottom,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: const Color(0xFFD8D5C9),
                  borderRadius: BorderRadius.circular(999),
                ),
              ),
            ),
            const SizedBox(height: 12),
            Text('Edit proposal',
                style: Theme.of(context).textTheme.titleMedium),
            if (widget.proposal.verifierDiffs.isNotEmpty) ...[
              const SizedBox(height: 8),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: _warnBg,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: _warnBorder),
                ),
                child: const Text(
                  'The second reading disagreed on the highlighted fields. '
                  'Check them against the document.',
                  style: TextStyle(color: _warnInk, height: 1.4),
                ),
              ),
            ],
            const SizedBox(height: 12),
            _moneyField(field: 'supplier', label: 'Supplier', controller: _supplier),
            const SizedBox(height: 12),
            _label('Date'),
            Container(
              decoration: (dateProblem != null || dateSecond != null)
                  ? BoxDecoration(
                      color: _warnBg,
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: _warnBorder),
                    )
                  : null,
              padding: (dateProblem != null || dateSecond != null)
                  ? const EdgeInsets.all(8)
                  : EdgeInsets.zero,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(child: Text(dateLabel)),
                      TextButton(
                        style: TextButton.styleFrom(
                            minimumSize: const Size(48, 48)),
                        onPressed: _pickDate,
                        child: const Text('Change'),
                      ),
                    ],
                  ),
                  if (dateSecond != null)
                    Text(
                      'Second reading disagrees: $dateSecond',
                      style: const TextStyle(color: _warnInk, fontSize: 13),
                    ),
                  if (dateProblem != null)
                    Text(
                      dateProblem.message,
                      style: const TextStyle(
                          color: _warnInk,
                          fontSize: 13,
                          fontWeight: FontWeight.w700),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 4),
            _moneyField(field: 'net', label: 'Net (£)', controller: _net),
            const SizedBox(height: 12),
            _moneyField(field: 'vat', label: 'VAT (£)', controller: _vat),
            const SizedBox(height: 12),
            _moneyField(
                field: 'gross', label: 'Gross (£)', controller: _gross),
            const SizedBox(height: 12),
            _moneyField(field: 'vrn', label: 'VAT number', controller: _vrn),
            const SizedBox(height: 12),
            _label('VAT code'),
            DropdownButtonFormField<String>(
              initialValue: _vatCode,
              isExpanded: true,
              items: [
                for (final code in kVatCodes)
                  DropdownMenuItem(
                      value: code, child: Text(_codeLabel(code))),
              ],
              onChanged: (value) {
                if (value != null) setState(() => _vatCode = value);
              },
              decoration: _decoration(null),
            ),
            const SizedBox(height: 12),
            _label('Category'),
            DropdownButtonFormField<String>(
              initialValue: _category,
              isExpanded: true,
              items: [
                for (final category in kCategories)
                  DropdownMenuItem(
                      value: category, child: Text(category)),
              ],
              onChanged: (value) {
                if (value != null) setState(() => _category = value);
              },
              decoration: _decoration(null),
            ),
            if (status != null) ...[
              const SizedBox(height: 12),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: _warnBg,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: _warnBorder),
                ),
                child: Text(status,
                    style:
                        const TextStyle(color: _warnInk, height: 1.4)),
              ),
            ],
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  flex: 2,
                  child: TextButton(
                    style: TextButton.styleFrom(
                      minimumSize: const Size.fromHeight(52),
                      padding:
                          const EdgeInsets.symmetric(horizontal: 8),
                    ),
                    onPressed: () => Navigator.of(context).pop(),
                    child: const Text('Cancel', softWrap: false),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  flex: 3,
                  child: FilledButton(
                    style: FilledButton.styleFrom(
                      backgroundColor: AccnomosColors.teal,
                      minimumSize: const Size.fromHeight(52),
                      padding:
                          const EdgeInsets.symmetric(horizontal: 8),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14)),
                    ),
                    onPressed: problems.isNotEmpty ? null : _save,
                    child: const Text('Save & approve',
                        softWrap: false,
                        style: TextStyle(fontWeight: FontWeight.w800)),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _moneyField({
    required String field,
    required String label,
    required TextEditingController controller,
  }) {
    final problem = _problemFor(field);
    final second = _disagreed(field);
    final highlight = problem != null || second != null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _label(label),
        TextField(
          controller: controller,
          autocorrect: false,
          keyboardType: field == 'supplier' || field == 'vrn'
              ? null
              : const TextInputType.numberWithOptions(decimal: true),
          inputFormatters: field == 'supplier' || field == 'vrn'
              ? null
              : [
                  FilteringTextInputFormatter.allow(RegExp(r'[0-9.,£ ]'))
                ],
          onChanged: (_) => setState(() {}),
          decoration: _decoration(
            field == 'supplier'
                ? 'e.g. Screwfix'
                : field == 'vrn'
                    ? 'e.g. GB 123 4567 89'
                    : '0.00',
          ).copyWith(
            filled: true,
            fillColor: highlight ? _warnBg : Colors.white,
          ),
        ),
        if (second != null)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              'Second reading disagrees: $second',
              style: const TextStyle(color: _warnInk, fontSize: 13),
            ),
          ),
        if (problem != null)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              problem.message,
              style: const TextStyle(
                  color: _warnInk,
                  fontSize: 13,
                  fontWeight: FontWeight.w700),
            ),
          ),
      ],
    );
  }

  Widget _label(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Text(text,
          style: const TextStyle(
              fontWeight: FontWeight.w700, color: AccnomosColors.ink)),
    );
  }

  InputDecoration _decoration(String? hint) {
    return InputDecoration(
      filled: true,
      fillColor: Colors.white,
      hintText: hint,
      contentPadding:
          const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      border:
          OutlineInputBorder(borderRadius: BorderRadius.circular(14)),
    );
  }

  String _codeLabel(String code) {
    switch (code) {
      case 'S':
        return 'S — standard 20%';
      case 'R':
        return 'R — reduced 5%';
      case 'Z':
        return 'Z — zero-rated';
      case 'E':
        return 'E — exempt';
      case 'O':
        return 'O — outside scope';
      case 'N':
        return 'N — no VAT';
      default:
        return code;
    }
  }
}
