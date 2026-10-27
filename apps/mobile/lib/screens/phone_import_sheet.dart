import 'package:flutter/material.dart';

import '../services/phone_contacts.dart';
import '../theme.dart';

/// Review the phone-picked contacts before importing, like the Outlook
/// import review: each picked person is marked Customer, Supplier or Skip,
/// then Import saves them through `POST /contacts/import-phone`.
/// Nothing is written back to the phone.
class PhoneImportSheet extends StatefulWidget {
  const PhoneImportSheet({
    super.key,
    required this.initialPicks,
    required this.onPickAnother,
    required this.onImport,
  });

  /// The contacts picked so far (the sheet owns the Customer/Supplier/Skip
  /// choice per person from here on).
  final List<PickedPhoneContact> initialPicks;

  /// Opens the system picker again for "Pick another".
  final Future<PickedPhoneContact?> Function() onPickAnother;

  /// Saves the reviewed body; returns the runtime's import summary
  /// (`read`, `matched`, `updated`, `added`, `skipped`).
  final Future<Map<String, dynamic>> Function(
      List<Map<String, String?>> body) onImport;

  /// One-line privacy note shown at the top of the sheet.
  static const privacyNote =
      'Only the contacts you pick are read; they are saved to your books on OneDrive.';

  @override
  State<PhoneImportSheet> createState() => _PhoneImportSheetState();
}

enum _Kind { customer, supplier, skip }

class _PhoneImportSheetState extends State<PhoneImportSheet> {
  late final List<PickedPhoneContact> _picks = List.of(widget.initialPicks);
  late final List<_Kind> _kinds = List.filled(
      widget.initialPicks.length, _Kind.customer,
      growable: true);
  bool _busy = false;
  String? _error;
  String? _done;

  int get _importCount =>
      _kinds.where((kind) => kind != _Kind.skip).length;

  Future<void> _pickAnother() async {
    if (_busy) return;
    PickedPhoneContact? next;
    try {
      next = await widget.onPickAnother();
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
      return;
    }
    if (next == null || !mounted) return;
    final pick = next;
    final name = pick.name.trim().toLowerCase();
    if (_picks.any((p) => p.name.trim().toLowerCase() == name)) {
      setState(() => _error = '${pick.name} is already in the list.');
      return;
    }
    setState(() {
      _picks.add(pick);
      _kinds.add(_Kind.customer);
      _error = null;
    });
  }

  Future<void> _import() async {
    if (_busy || _importCount == 0) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final body = <Map<String, String?>>[
      for (var i = 0; i < _picks.length; i++)
        if (_kinds[i] != _Kind.skip)
          _picks[i].toImportJson(
              _kinds[i] == _Kind.supplier ? 'supplier' : 'customer'),
    ];
    try {
      final result = await widget.onImport(body);
      if (!mounted) return;
      final added = (result['added'] ?? 0) as num;
      final updated = (result['updated'] ?? 0) as num;
      setState(() {
        _done = 'Imported ${_plural(added, 'contact')} '
            '(${_plural(updated, 'contact')} updated).';
      });
    } catch (e) {
      if (!mounted) return;
      setState(
          () => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  static String _plural(num n, String one) =>
      n == 1 ? '1 $one' : '$n ${one}s';

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.only(
          left: 16,
          right: 16,
          top: 12,
          bottom: 16 + MediaQuery.of(context).viewInsets.bottom,
        ),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Add from phone',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 4),
              const Text(
                PhoneImportSheet.privacyNote,
                style: TextStyle(color: AccnomosColors.muted),
              ),
              const SizedBox(height: 12),
              for (var i = 0; i < _picks.length; i++) ...[
                _pickCard(i),
                const SizedBox(height: 8),
              ],
              OutlinedButton.icon(
                onPressed: _busy || _done != null ? null : _pickAnother,
                icon: const Icon(Icons.person_add_outlined),
                label: const Text('Pick another'),
              ),
              if (_error != null) ...[
                const SizedBox(height: 8),
                Text(_error!,
                    style:
                        const TextStyle(color: AccnomosColors.muted)),
              ],
              if (_done != null) ...[
                const SizedBox(height: 8),
                Text(_done!,
                    style: const TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 8),
                FilledButton(
                  style: FilledButton.styleFrom(
                    backgroundColor: AccnomosColors.teal,
                    minimumSize: const Size.fromHeight(48),
                  ),
                  onPressed: () => Navigator.of(context).pop(true),
                  child: const Text('Done'),
                ),
              ] else ...[
                const SizedBox(height: 8),
                FilledButton(
                  style: FilledButton.styleFrom(
                    backgroundColor: AccnomosColors.teal,
                    minimumSize: const Size.fromHeight(48),
                  ),
                  onPressed: _busy || _importCount == 0 ? null : _import,
                  child: Text(_busy
                      ? 'Importing…'
                      : 'Import $_importCount'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _pickCard(int index) {
    final pick = _picks[index];
    final details = [
      if (pick.email.isNotEmpty) pick.email,
      if (pick.phone.isNotEmpty) pick.phone,
      if ((pick.address ?? '').trim().isNotEmpty) pick.address!.trim(),
    ].join('\n');
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              pick.name,
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
            if (details.isNotEmpty) ...[
              const SizedBox(height: 2),
              Text(details,
                  style:
                      const TextStyle(color: AccnomosColors.muted)),
            ],
            const SizedBox(height: 8),
            SegmentedButton<_Kind>(
              segments: const [
                ButtonSegment(
                    value: _Kind.customer, label: Text('Customer')),
                ButtonSegment(
                    value: _Kind.supplier, label: Text('Supplier')),
                ButtonSegment(value: _Kind.skip, label: Text('Skip')),
              ],
              selected: {_kinds[index]},
              onSelectionChanged: _busy || _done != null
                  ? null
                  : (selection) =>
                      setState(() => _kinds[index] = selection.first),
              showSelectedIcon: false,
              style: SegmentedButton.styleFrom(
                visualDensity: VisualDensity.compact,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
