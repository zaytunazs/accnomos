import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/books.dart';
import '../services/settings.dart';
import '../theme.dart';
import 'invoice_send.dart';

const _vatLabels = {
  'S': 'Standard 20%',
  'R': 'Reduced 5%',
  'Z': 'Zero rated',
  'E': 'Exempt',
  'O': 'Outside scope',
};

/// Quick invoice form: pick a customer, add one or more lines with a VAT
/// code, then preview the runtime's totals before sending. The phone never
/// prices a line itself.
class NewInvoiceScreen extends StatefulWidget {
  const NewInvoiceScreen({
    super.key,
    required this.settings,
    required this.auth,
    required this.account,
  });

  final AppSettings settings;
  final AuthService auth;
  final Account? account;

  @override
  State<NewInvoiceScreen> createState() => _NewInvoiceScreenState();
}

class _LineState {
  final TextEditingController description = TextEditingController();
  final TextEditingController qty =
      TextEditingController(text: '1');
  final TextEditingController unitPrice = TextEditingController();
  String vatCode = 'S';

  void dispose() {
    description.dispose();
    qty.dispose();
    unitPrice.dispose();
  }
}

class _NewInvoiceScreenState extends State<NewInvoiceScreen> {
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _address = TextEditingController();
  final _reference = TextEditingController();
  final _notes = TextEditingController();
  final _lines = [_LineState()];
  List<Map<String, dynamic>> _customers = const [];
  Map<String, dynamic>? _picked;
  bool _loadingCustomers = true;
  bool _working = false;
  String? _error;
  Map<String, dynamic>? _created;
  Map<String, dynamic>? _sent;

  @override
  void initState() {
    super.initState();
    _loadCustomers();
  }

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _address.dispose();
    _reference.dispose();
    _notes.dispose();
    for (final l in _lines) {
      l.dispose();
    }
    super.dispose();
  }

  Future<void> _loadCustomers() async {
    try {
      final client = await booksClient(
          widget.settings, widget.auth, widget.account);
      final rows = await client.invoiceCustomers();
      if (!mounted) return;
      setState(() {
        _customers = rows;
        _loadingCustomers = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _loadingCustomers = false);
    }
  }

  void _pickCustomer(Map<String, dynamic>? customer) {
    setState(() => _picked = customer);
    if (customer != null) {
      _name.text = (customer['name'] ?? '').toString();
      _email.text = (customer['email'] ?? '').toString();
      _address.text = (customer['address'] ?? '').toString();
    }
  }

  /// Validated draft, or null (with the reason shown).
  Map<String, dynamic>? _draft() {
    final name = _name.text.trim();
    if (name.isEmpty) {
      setState(
          () => _error = 'Choose a customer or type a name.');
      return null;
    }
    final lines = <Map<String, dynamic>>[];
    for (var i = 0; i < _lines.length; i++) {
      final line = _lines[i];
      final desc = line.description.text.trim();
      final qty = double.tryParse(line.qty.text.trim());
      final price =
          double.tryParse(line.unitPrice.text.trim());
      if (desc.isEmpty || qty == null || qty <= 0) {
        setState(() => _error =
            'Line ${i + 1} needs a description and a quantity above 0.');
        return null;
      }
      if (price == null) {
        setState(() => _error =
            'Line ${i + 1} needs a unit price in pounds.');
        return null;
      }
      lines.add({
        'description': desc,
        'quantity': line.qty.text.trim(),
        'unit': null,
        'unit_price_pence': (price * 100).round(),
        'vat_code': line.vatCode,
      });
    }
    if (lines.isEmpty) {
      setState(() => _error = 'Add at least one line.');
      return null;
    }
    final pickedId = _picked == null
        ? null
        : (_picked!['contact_id'] ?? _picked!['id'])?.toString();
    final pickedName = (_picked?['name'] ?? '').toString();
    return {
      'customer': {
        if (pickedId != null &&
            pickedId.isNotEmpty &&
            pickedName == name)
          'contact_id': pickedId,
        'name': name,
        'email':
            _email.text.trim().isEmpty ? null : _email.text.trim(),
        'address': _address.text.trim().isEmpty
            ? null
            : _address.text.trim(),
      },
      'issue_date': null,
      'due_date': null,
      'lines': lines,
      'reference': _reference.text.trim().isEmpty
          ? null
          : _reference.text.trim(),
      'notes': _notes.text.trim().isEmpty
          ? null
          : _notes.text.trim(),
    };
  }

  Future<void> _preview() async {
    final draft = _draft();
    if (draft == null || _working) return;
    setState(() {
      _working = true;
      _error = null;
    });
    try {
      final client = await booksClient(
          widget.settings, widget.auth, widget.account);
      final created = await client.createInvoice(draft);
      if (!mounted) return;
      setState(() => _created = created);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  Future<void> _send() async {
    final number = (_created?['number'] ?? '').toString();
    if (number.isEmpty || _working) return;
    setState(() {
      _working = true;
      _error = null;
    });
    try {
      final sent = await confirmAndSend(
        context,
        settings: widget.settings,
        auth: widget.auth,
        account: widget.account,
        number: number,
      );
      if (!mounted) return;
      if (sent != null) setState(() => _sent = sent);
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final created = _created;
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          'New invoice',
          style: Theme.of(context).textTheme.titleMedium,
        ),
      ),
      body: created == null ? _formView() : _previewView(created),
    );
  }

  Widget _formView() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('Customer',
            style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        DropdownButtonFormField<Map<String, dynamic>>(
          initialValue: _picked,
          decoration: const InputDecoration(
            labelText: 'Pick a customer',
            border: OutlineInputBorder(),
            filled: true,
            fillColor: Colors.white,
          ),
          items: [
            if (_loadingCustomers)
              const DropdownMenuItem(
                  value: null,
                  child: Text('Loading…'))
            else ...[
              for (final c in _customers)
                DropdownMenuItem(
                  value: c,
                  child: Text(
                      (c['name'] ?? 'Unnamed').toString()),
                ),
            ],
          ],
          onChanged: _loadingCustomers ? null : _pickCustomer,
        ),
        const SizedBox(height: 10),
        TextField(
          controller: _name,
          decoration: const InputDecoration(
            labelText: 'Name',
            border: OutlineInputBorder(),
            filled: true,
            fillColor: Colors.white,
          ),
        ),
        const SizedBox(height: 10),
        TextField(
          controller: _email,
          keyboardType: TextInputType.emailAddress,
          decoration: const InputDecoration(
            labelText: 'Email (for sending)',
            border: OutlineInputBorder(),
            filled: true,
            fillColor: Colors.white,
          ),
        ),
        const SizedBox(height: 10),
        TextField(
          controller: _address,
          maxLines: 2,
          minLines: 1,
          decoration: const InputDecoration(
            labelText: 'Address (optional)',
            border: OutlineInputBorder(),
            filled: true,
            fillColor: Colors.white,
            alignLabelWithHint: true,
          ),
        ),
        const SizedBox(height: 20),
        Text('Lines',
            style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        for (var i = 0; i < _lines.length; i++)
          _lineCard(i, _lines[i]),
        OutlinedButton.icon(
          icon: const Icon(Icons.add_outlined),
          label: const Text('Add line'),
          style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(48)),
          onPressed: _working
              ? null
              : () => setState(
                  () => _lines.add(_LineState())),
        ),
        const SizedBox(height: 20),
        Text('Details',
            style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        TextField(
          controller: _reference,
          decoration: const InputDecoration(
            labelText: 'Reference (optional)',
            border: OutlineInputBorder(),
            filled: true,
            fillColor: Colors.white,
          ),
        ),
        const SizedBox(height: 10),
        TextField(
          controller: _notes,
          maxLines: 3,
          minLines: 1,
          decoration: const InputDecoration(
            labelText: 'Notes (optional)',
            border: OutlineInputBorder(),
            filled: true,
            fillColor: Colors.white,
            alignLabelWithHint: true,
          ),
        ),
        if (_error != null) ...[
          const SizedBox(height: 12),
          Text(_error!,
              style: const TextStyle(
                  color: Color(0xFF8A3F06), height: 1.4)),
        ],
        const SizedBox(height: 16),
        FilledButton(
          style: FilledButton.styleFrom(
            backgroundColor: AccnomosColors.teal,
            minimumSize: const Size.fromHeight(52),
          ),
          onPressed: _working ? null : _preview,
          child: Text(_working ? 'Working…' : 'Preview totals'),
        ),
      ],
    );
  }

  Widget _lineCard(int index, _LineState line) {
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text('Line ${index + 1}',
                      style: const TextStyle(
                          fontWeight: FontWeight.w700)),
                ),
                if (_lines.length > 1)
                  IconButton(
                    icon:
                        const Icon(Icons.delete_outline),
                    tooltip: 'Remove line',
                    constraints: const BoxConstraints(
                        minWidth: 48, minHeight: 48),
                    onPressed: _working
                        ? null
                        : () => setState(() {
                              _lines.removeAt(index);
                              line.dispose();
                            }),
                  ),
              ],
            ),
            TextField(
              controller: line.description,
              decoration: const InputDecoration(
                labelText: 'Description',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: line.qty,
                    keyboardType:
                        const TextInputType.numberWithOptions(
                            decimal: true),
                    decoration: const InputDecoration(
                      labelText: 'Qty',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: TextField(
                    controller: line.unitPrice,
                    keyboardType:
                        const TextInputType.numberWithOptions(
                            decimal: true),
                    decoration: const InputDecoration(
                      labelText: 'Unit price (£)',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            DropdownButtonFormField<String>(
              initialValue: line.vatCode,
              decoration: const InputDecoration(
                labelText: 'VAT code',
                border: OutlineInputBorder(),
              ),
              items: [
                for (final code in _vatLabels.keys)
                  DropdownMenuItem(
                    value: code,
                    child: Text(
                        '$code · ${_vatLabels[code]}'),
                  ),
              ],
              onChanged: (code) {
                if (code != null) {
                  setState(() => line.vatCode = code);
                }
              },
            ),
          ],
        ),
      ),
    );
  }

  /// Totals below come from the runtime's response, never from the phone.
  Widget _previewView(Map<String, dynamic> created) {
    final sent = _sent;
    final status = ((sent ?? created)['status'] ?? '').toString();
    final sentTo = ((sent ?? created)['sent_to'] ?? '').toString();
    final vatSummary = (created['vat_summary'] as List?) ?? const [];
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(16),
            border:
                Border.all(color: const Color(0xFFE3E1D8)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Draft ${(created['number'] ?? '').toString()} saved',
                style: Theme.of(context)
                    .textTheme
                    .titleMedium,
              ),
              const SizedBox(height: 2),
              Text(
                'Status: $status'
                '${sentTo.isNotEmpty ? ' · sent to $sentTo' : ''}',
                style: const TextStyle(
                    color: AccnomosColors.muted),
              ),
              const Divider(height: 24),
              _totalRow(
                  'Net', (created['net_pence'] ?? 0) as num),
              const SizedBox(height: 4),
              _totalRow(
                  'VAT', (created['vat_pence'] ?? 0) as num),
              const SizedBox(height: 4),
              _totalRow(
                  'Total', (created['total_pence'] ?? 0) as num,
                  bold: true),
              for (final row in vatSummary)
                if (row is Map)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(
                      'VAT ${(row['vat_code'] ?? '').toString()}: '
                      '${gbp((row['vat_pence'] ?? 0) as num)}',
                      style: const TextStyle(
                          color: AccnomosColors.muted,
                          fontSize: 12),
                    ),
                  ),
            ],
          ),
        ),
        if (_error != null) ...[
          const SizedBox(height: 12),
          Text(_error!,
              style: const TextStyle(
                  color: Color(0xFF8A3F06), height: 1.4)),
        ],
        const SizedBox(height: 16),
        if (sent == null)
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: AccnomosColors.teal,
              minimumSize: const Size.fromHeight(52),
            ),
            onPressed: _working ? null : _send,
            child: const Text('Send via Outlook'),
          )
        else
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: AccnomosColors.teal,
              minimumSize: const Size.fromHeight(52),
            ),
            onPressed: () =>
                Navigator.of(context).pop(true),
            child: const Text('Done'),
          ),
      ],
    );
  }

  Widget _totalRow(String label, num pence, {bool bold = false}) {
    final style = TextStyle(
      fontWeight: bold ? FontWeight.w800 : FontWeight.w600,
      fontSize: bold ? 17 : 14,
    );
    return Row(
      children: [
        Expanded(child: Text(label, style: style)),
        Text(gbp(pence), style: style),
      ],
    );
  }
}
