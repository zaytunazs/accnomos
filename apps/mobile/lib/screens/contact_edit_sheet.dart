import 'package:flutter/material.dart';

import '../theme.dart';
import '../widgets/lookups.dart';

/// Edit a contact's name, company number and registered address. A
/// [CompanyLookupSection] fills the three fields when [companiesHouse] is
/// true; nothing is saved until Save. Returns the edits on pop, null on
/// cancel.
class ContactEditSheet extends StatefulWidget {
  const ContactEditSheet({
    super.key,
    required this.initialName,
    required this.initialCompanyNumber,
    required this.initialAddress,
    required this.companiesHouse,
    required this.onSearch,
  });

  final String initialName;
  final String initialCompanyNumber;
  final String initialAddress;

  /// False when the runtime answered 503 `companies_house_not_configured`:
  /// the look-up stays hidden.
  final bool companiesHouse;

  /// Companies House matches for a name or number (the reader's
  /// `GET /lookup/companies`).
  final Future<List<Map<String, dynamic>>> Function(String q) onSearch;

  @override
  State<ContactEditSheet> createState() => _ContactEditState();
}

class _ContactEditState extends State<ContactEditSheet> {
  final _name = TextEditingController();
  final _number = TextEditingController();
  final _address = TextEditingController();
  bool _companiesHouse = true;
  String? _nameError;

  @override
  void initState() {
    super.initState();
    _name.text = widget.initialName;
    _number.text = widget.initialCompanyNumber;
    _address.text = widget.initialAddress;
    _companiesHouse = widget.companiesHouse;
  }

  @override
  void dispose() {
    _name.dispose();
    _number.dispose();
    _address.dispose();
    super.dispose();
  }

  void _pick(Map<String, dynamic> m) {
    setState(() {
      _name.text = (m['name'] ?? '').toString();
      _number.text = (m['company_number'] ?? '').toString();
      final address = (m['address'] ?? '').toString();
      if (address.isNotEmpty) _address.text = address;
    });
  }

  void _save() {
    if (_name.text.trim().isEmpty) {
      setState(() => _nameError = 'Give the contact a name.');
      return;
    }
    Navigator.of(context).pop({
      'name': _name.text.trim(),
      'company_number':
          _number.text.trim().isEmpty ? null : _number.text.trim(),
      'address': _address.text.trim().isEmpty ? null : _address.text.trim(),
    });
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SingleChildScrollView(
        padding: EdgeInsets.only(
          left: 16,
          right: 16,
          top: 16,
          bottom: 16 + MediaQuery.of(context).viewInsets.bottom,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'Edit contact',
              style: TextStyle(fontWeight: FontWeight.w800, fontSize: 18),
            ),
            const SizedBox(height: 12),
            if (_companiesHouse)
              CompanyLookupSection(
                initialQuery: _number.text.trim().isNotEmpty
                    ? _number.text.trim()
                    : _name.text.trim(),
                onSearch: widget.onSearch,
                onPick: _pick,
                onNotConfigured: () =>
                    setState(() => _companiesHouse = false),
              ),
            if (_companiesHouse) const SizedBox(height: 12),
            TextField(
              controller: _name,
              decoration: InputDecoration(
                labelText: 'Name',
                errorText: _nameError,
                border: const OutlineInputBorder(),
                filled: true,
                fillColor: Colors.white,
              ),
              onChanged: (_) {
                if (_nameError != null) {
                  setState(() => _nameError = null);
                }
              },
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _number,
              decoration: const InputDecoration(
                labelText: 'Company number',
                hintText: '01234567 or SC123456',
                border: OutlineInputBorder(),
                filled: true,
                fillColor: Colors.white,
              ),
              textCapitalization: TextCapitalization.characters,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _address,
              decoration: const InputDecoration(
                labelText: 'Registered address',
                border: OutlineInputBorder(),
                filled: true,
                fillColor: Colors.white,
              ),
              maxLines: 3,
              minLines: 1,
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: FilledButton(
                    style: FilledButton.styleFrom(
                      backgroundColor: AccnomosColors.teal,
                      minimumSize: const Size.fromHeight(52),
                    ),
                    onPressed: _save,
                    child: const Text('Save'),
                  ),
                ),
                const SizedBox(width: 8),
                TextButton(
                  style: TextButton.styleFrom(
                    foregroundColor: AccnomosColors.tealDark,
                    minimumSize: const Size(48, 52),
                  ),
                  onPressed: () => Navigator.of(context).pop(),
                  child: const Text('Cancel'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
