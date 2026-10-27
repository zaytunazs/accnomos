import 'package:flutter/material.dart';

import '../theme.dart';

const _matchOps = ['contains', 'equals', 'regex'];
const _directions = ['out', 'in', 'either'];
const _vatCodes = ['S', 'R', 'Z', 'E', 'O', 'N'];

/// Pence from a pounds string ("12.34" → 1234, "" → null).
int? rulePence(String text) {
  final t = text.trim().replaceAll('£', '').replaceAll(',', '');
  if (t.isEmpty) return null;
  final n = (double.tryParse(t) ?? double.nan) * 100;
  return n.isFinite ? n.round() : null;
}

/// Add/edit sheet for one bank rule: "when the description contains X,
/// code it to Y". Pure form — the caller posts [onSave] to
/// `createBankRule`/`updateBankRule` and shows the refusal sentence.
/// [initial] is a rule as `bankRules()` returned, or null for a new one.
class BankRuleSheet extends StatefulWidget {
  const BankRuleSheet({super.key, this.initial, required this.onSave});

  final Map<String, dynamic>? initial;
  final Future<String?> Function(Map<String, dynamic> body) onSave;

  @override
  State<BankRuleSheet> createState() => _BankRuleSheetState();
}

class _BankRuleSheetState extends State<BankRuleSheet> {
  late final TextEditingController _name;
  late final TextEditingController _value;
  late final TextEditingController _min;
  late final TextEditingController _max;
  late final TextEditingController _account;
  late final TextEditingController _contact;
  late final TextEditingController _jobId;
  late String _op;
  late String _direction;
  String? _vatCode;
  bool _saving = false;
  String? _error;

  static Map<String, dynamic> _mapOf(Object? value) =>
      value is Map ? Map<String, dynamic>.from(value) : {};

  static String _pounds(Object? pence) {
    if (pence == null) return '';
    final n = pence is num ? pence.toDouble() : double.tryParse('$pence');
    if (n == null) return '';
    return (n / 100).toString();
  }

  @override
  void initState() {
    super.initState();
    final initial = widget.initial ?? {};
    final match = _mapOf(initial['match']);
    final action = _mapOf(initial['action']);
    _name = TextEditingController(text: (initial['name'] ?? '').toString());
    _value = TextEditingController(text: (match['value'] ?? '').toString());
    _min = TextEditingController(
        text: _pounds(initial['amount_min_pence']));
    _max = TextEditingController(
        text: _pounds(initial['amount_max_pence']));
    _account =
        TextEditingController(text: (action['account'] ?? '').toString());
    _contact =
        TextEditingController(text: (action['contact'] ?? '').toString());
    _jobId =
        TextEditingController(text: (action['job_id'] ?? '').toString());
    _op = _matchOps.contains(match['op']) ? match['op'].toString() : 'contains';
    _direction = _directions.contains(initial['direction'])
        ? initial['direction'].toString()
        : 'out';
    final vat = (action['vat_code'] ?? '').toString().toUpperCase();
    _vatCode = _vatCodes.contains(vat) ? vat : null;
  }

  @override
  void dispose() {
    _name.dispose();
    _value.dispose();
    _min.dispose();
    _max.dispose();
    _account.dispose();
    _contact.dispose();
    _jobId.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_saving) return;
    final value = _value.text.trim();
    final account = _account.text.trim();
    if (value.isEmpty) {
      setState(() => _error = 'Type the text to match on.');
      return;
    }
    if (account.isEmpty) {
      setState(() => _error = 'Choose the account to code it to.');
      return;
    }
    final body = {
      'name': _name.text.trim(),
      'match': {'op': _op, 'value': value},
      'amount_min_pence': rulePence(_min.text),
      'amount_max_pence': rulePence(_max.text),
      'direction': _direction,
      'action': {
        'account': account,
        'vat_code': _vatCode,
        'contact':
            _contact.text.trim().isEmpty ? null : _contact.text.trim(),
        'job_id': _jobId.text.trim().isEmpty ? null : _jobId.text.trim(),
      },
    };
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final problem = await widget.onSave(body);
      if (!mounted) return;
      if (problem != null) {
        setState(() => _error = problem);
      } else {
        Navigator.of(context).pop(true);
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SingleChildScrollView(
        padding: EdgeInsets.only(
          left: 16,
          right: 16,
          top: 16,
          bottom: MediaQuery.of(context).viewInsets.bottom + 16,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              widget.initial == null ? 'New bank rule' : 'Edit bank rule',
              style: const TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: 18,
                  color: AccnomosColors.ink),
            ),
            const SizedBox(height: 4),
            const Text('When the description matches, code it to the account below.',
                style: TextStyle(color: AccnomosColors.muted, fontSize: 13)),
            const SizedBox(height: 12),
            _field('Rule name (for you)', _name),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: _dropdown<String>(
                    label: 'Match type',
                    value: _op,
                    items: const {
                      'contains': 'contains',
                      'equals': 'is exactly',
                      'regex': 'matches pattern',
                    },
                    onChanged: (v) => setState(() => _op = v),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _dropdown<String>(
                    label: 'Direction',
                    value: _direction,
                    items: const {
                      'out': 'Money out',
                      'in': 'Money in',
                      'either': 'Either way',
                    },
                    onChanged: (v) => setState(() => _direction = v),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            _field('Match this text', _value),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(child: _field('Amount from (£, optional)', _min,
                    number: true)),
                const SizedBox(width: 8),
                Expanded(child: _field('Amount to (£, optional)', _max,
                    number: true)),
              ],
            ),
            const SizedBox(height: 8),
            _field('Code it to (account)', _account),
            const SizedBox(height: 8),
            _dropdown<String?>(
              label: 'VAT code',
              value: _vatCode,
              items: const {
                null: 'None',
                'S': 'S · 20%',
                'R': 'R · 5%',
                'Z': 'Z · 0%',
                'E': 'E · Exempt',
                'O': 'O · Outside scope',
                'N': 'N · No VAT',
              },
              onChanged: (v) => setState(() => _vatCode = v),
            ),
            const SizedBox(height: 8),
            _field('Contact (optional)', _contact),
            const SizedBox(height: 8),
            _field('Job id (optional)', _jobId),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(_error!,
                  style: const TextStyle(
                      color: Color(0xFF8A3F06),
                      fontWeight: FontWeight.w700,
                      fontSize: 13)),
            ],
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size.fromHeight(52),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14)),
                ),
                onPressed: _saving ? null : _save,
                child: _saving
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white))
                    : const Text('Save rule',
                        style: TextStyle(
                            fontWeight: FontWeight.w800, fontSize: 16)),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _field(String label, TextEditingController controller,
      {bool number = false}) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w700,
                color: AccnomosColors.muted)),
        const SizedBox(height: 4),
        TextField(
          controller: controller,
          keyboardType: number ? TextInputType.number : null,
          decoration: InputDecoration(
            border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12)),
            contentPadding:
                const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
          ),
        ),
      ],
    );
  }

  Widget _dropdown<T>({
    required String label,
    required T value,
    required Map<T, String> items,
    required ValueChanged<T> onChanged,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w700,
                color: AccnomosColors.muted)),
        const SizedBox(height: 4),
        DropdownButtonFormField<T>(
          initialValue: value,
          isExpanded: true,
          items: [
            for (final e in items.entries)
              DropdownMenuItem(value: e.key, child: Text(e.value)),
          ],
          onChanged: (v) {
            if (v != null || items.containsKey(null)) onChanged(v as T);
          },
          decoration: InputDecoration(
            border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12)),
            contentPadding:
                const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
          ),
        ),
      ],
    );
  }
}
