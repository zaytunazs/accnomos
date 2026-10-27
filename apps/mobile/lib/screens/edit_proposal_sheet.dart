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
/// the signed-out preview. The VAT code is validated here but never sent —
/// the runtime has no such field.
class EditResult {
  EditResult({required this.edits, required this.updated});
  final Map<String, dynamic> edits;
  final Proposal updated;
}

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

  late final String? _initialDateIso;
  late String? _dateIso;
  bool _dateTouched = false;

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
    super.dispose();
  }

  int? get _netPence => parsePoundsToPence(_net.text);
  int? get _vatPence => parsePoundsToPence(_vat.text);
  int? get _grossPence => parsePoundsToPence(_gross.text);

  /// Parse or totals problems that block saving; null when the sheet is valid.
  String? get _problem {
    if (_supplier.text.trim().isEmpty) {
      return 'Enter the supplier name.';
    }
    final net = _netPence;
    final vat = _vatPence;
    final gross = _grossPence;
    if (net == null || vat == null || gross == null) {
      return 'Net, VAT and gross must all be amounts, e.g. 32.06.';
    }
    return totalsDiscrepancy(
            netPence: net, vatPence: vat, grossPence: gross) ??
        vatRateDiscrepancy(code: _vatCode, netPence: net, vatPence: vat);
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
    final problem = _problem;
    if (problem != null) return;
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
    final problem = _problem;
    final dateLabel = formatDisplayDate(
        tryParseProposalDate(_dateIso ?? '') ?? DateTime.now());
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
            const SizedBox(height: 12),
            _label('Supplier'),
            TextField(
              controller: _supplier,
              autocorrect: false,
              onChanged: (_) => setState(() {}),
              decoration: _decoration('e.g. Screwfix'),
            ),
            const SizedBox(height: 12),
            _label('Date'),
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
            const SizedBox(height: 4),
            _label('Net (£)'),
            TextField(
              controller: _net,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp(r'[0-9.,£ ]'))
              ],
              onChanged: (_) => setState(() {}),
              decoration: _decoration('0.00'),
            ),
            const SizedBox(height: 12),
            _label('VAT (£)'),
            TextField(
              controller: _vat,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp(r'[0-9.,£ ]'))
              ],
              onChanged: (_) => setState(() {}),
              decoration: _decoration('0.00'),
            ),
            const SizedBox(height: 12),
            _label('Gross (£)'),
            TextField(
              controller: _gross,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp(r'[0-9.,£ ]'))
              ],
              onChanged: (_) => setState(() {}),
              decoration: _decoration('0.00'),
            ),
            const SizedBox(height: 12),
            _label('VAT code'),
            DropdownButtonFormField<String>(
              initialValue: _vatCode,
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
            if (problem != null) ...[
              const SizedBox(height: 12),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: _warnBg,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: _warnBorder),
                ),
                child: Text(problem,
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
                    onPressed: problem != null ? null : _save,
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
