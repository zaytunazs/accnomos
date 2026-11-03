import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../services/demo.dart';
import '../services/phone_contacts.dart';
import '../theme.dart';

/// Where the rows come from.
enum ImportSource { phone, outlook, email }

extension ImportSourceText on ImportSource {
  String get id => switch (this) {
        ImportSource.phone => 'phone',
        ImportSource.outlook => 'outlook',
        ImportSource.email => 'email',
      };
  String get label => switch (this) {
        ImportSource.phone => 'Phone',
        ImportSource.outlook => 'Outlook',
        ImportSource.email => 'Email',
      };
}

/// One row offered for import (the runtime's `Candidate`).
class ImportCandidate {
  ImportCandidate({
    required this.ref,
    required this.name,
    this.person,
    this.email,
    this.phone,
    this.messages,
    this.existingName,
    this.match,
    this.existing = false,
    this.kind = 'customer',
  });

  factory ImportCandidate.fromJson(Map<String, dynamic> j) {
    String? s(Object? v) {
      final t = (v ?? '').toString().trim();
      return t.isEmpty ? null : t;
    }

    return ImportCandidate(
      ref: (j['ref'] ?? j['name'] ?? '').toString(),
      name: (j['name'] ?? '').toString(),
      person: s(j['person']),
      email: s(j['email']),
      phone: s(j['phone']),
      messages: j['messages'] is num ? (j['messages'] as num).toInt() : null,
      existingName: s(j['existing_name']),
      match: s(j['match']),
      existing: s(j['existing_id']) != null,
      kind: s(j['kind']) ?? 'customer',
    );
  }

  final String ref;
  final String name;
  final String? person;
  final String? email;
  final String? phone;
  final int? messages;
  final String? existingName;
  final String? match;
  final bool existing;
  String kind;

  Map<String, dynamic> toRow() => {
        'name': name,
        if (person != null) 'person': person,
        if (email != null) 'email': email,
        if (phone != null) 'phone': phone,
        'kind': kind,
      };

  String get details => [
        person,
        email,
        phone,
        if (messages != null) '$messages email${messages == 1 ? '' : 's'}',
      ].whereType<String>().join(' · ');
}

/// The phone's contacts as the rows `POST /contacts/import/check` takes:
/// the company as the name when there is one, the person kept alongside.
List<Map<String, dynamic>> phoneRows(List<PickedPhoneContact> contacts) => [
      for (final c in contacts)
        {
          'name': (c.company ?? '').isNotEmpty ? c.company : c.name,
          if ((c.company ?? '').isNotEmpty && c.company != c.name)
            'person': c.name,
          if (c.email.isNotEmpty) 'email': c.email,
          if (c.phone.isNotEmpty) 'phone': c.phone,
        },
    ];

/// What the screen calls; the Contacts screen passes the real ones, tests
/// pass fakes.
class ImportContactsApi {
  ImportContactsApi({
    required this.preview,
    required this.check,
    required this.save,
    required this.listPhone,
  });

  /// `GET /contacts/import/{outlook|email}` (asks for the Graph scope).
  final Future<Map<String, dynamic>> Function(ImportSource source) preview;

  /// `POST /contacts/import/check` for the phone's rows.
  final Future<Map<String, dynamic>> Function(List<Map<String, dynamic>> rows)
      check;

  /// `POST /contacts/import`.
  final Future<Map<String, dynamic>> Function(
      ImportSource source, List<Map<String, dynamic>> rows) save;

  /// The phone's address book (asks for the Contacts permission).
  final Future<List<PickedPhoneContact>> Function() listPhone;
}

/// Contacts › Import contacts: from the phone, Outlook or the people who
/// email you — all, or only the ones ticked. Rows already in the books start
/// unticked. Each row is a Customer, Supplier or Both. Pops `true` after an
/// import (the Contacts list reloads).
class ImportContactsScreen extends StatefulWidget {
  const ImportContactsScreen({super.key, required this.api, this.initial = ImportSource.phone});

  final ImportContactsApi api;
  final ImportSource initial;

  @override
  State<ImportContactsScreen> createState() => _ImportContactsScreenState();
}

class _ImportContactsScreenState extends State<ImportContactsScreen> {
  late ImportSource _source = widget.initial;
  List<ImportCandidate>? _rows;
  String? _note;
  String? _error;
  bool _loading = false;
  bool _saving = false;
  final Set<String> _picked = {};
  String _query = '';
  int _load = 0;

  @override
  void initState() {
    super.initState();
    _fetch();
  }

  Future<void> _fetch() async {
    final ticket = ++_load;
    setState(() {
      _loading = true;
      _error = null;
      _rows = null;
      _note = null;
      _picked.clear();
    });
    try {
      final Map<String, dynamic> p;
      if (_source == ImportSource.phone) {
        final phone = await widget.api.listPhone();
        p = phone.isEmpty
            ? {'candidates': const [], 'note': ''}
            : await widget.api.check(phoneRows(phone));
      } else {
        p = await widget.api.preview(_source);
      }
      if (!mounted || ticket != _load) return;
      final rows = [
        for (final c in (p['candidates'] as List? ?? const []))
          if (c is Map) ImportCandidate.fromJson(Map<String, dynamic>.from(c)),
      ];
      setState(() {
        _rows = rows;
        _note = (p['note'] ?? '').toString();
        _picked.addAll(rows.where((r) => !r.existing).map((r) => r.ref));
      });
    } on PlatformException catch (e) {
      if (!mounted || ticket != _load) return;
      setState(() => _error = e.code == 'DENIED'
          ? 'Accnomos needs permission to read your contacts to list them. '
              'You can allow it in Android Settings › Apps › Accnomos › Permissions.'
          : 'Could not read the phone’s contacts.');
    } catch (e) {
      if (!mounted || ticket != _load) return;
      setState(() => _error = 'Could not read that list. $e'.replaceAll('Exception: ', ''));
    } finally {
      if (mounted && ticket == _load) setState(() => _loading = false);
    }
  }

  List<ImportCandidate> get _shown {
    final q = _query.trim().toLowerCase();
    final all = _rows ?? const <ImportCandidate>[];
    if (q.isEmpty) return all;
    return all
        .where((r) => [r.name, r.person, r.email, r.phone]
            .any((v) => (v ?? '').toLowerCase().contains(q)))
        .toList();
  }

  List<ImportCandidate> get _chosen =>
      (_rows ?? const <ImportCandidate>[]).where((r) => _picked.contains(r.ref)).toList();

  Future<void> _save() async {
    final chosen = _chosen;
    if (chosen.isEmpty) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final s = await widget.api.save(_source, [for (final r in chosen) r.toRow()]);
      if (!mounted) return;
      final message = (s['message'] ?? 'Imported.').toString();
      await showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Contacts imported'),
          content: Text(message),
          actions: [TextButton(onPressed: () => Navigator.pop(c), child: const Text('Done'))],
        ),
      );
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) setState(() => _error = 'Could not import: $e'.replaceAll('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  void _setAllKinds(String kind) {
    setState(() {
      for (final r in _chosen) {
        r.kind = kind;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final rows = _rows;
    final demo = Demo.current != null;
    final existing = rows?.where((r) => r.existing).length ?? 0;
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(title: const Text('Import contacts')),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
            child: SegmentedButton<ImportSource>(
              segments: [
                for (final s in ImportSource.values)
                  ButtonSegment(value: s, label: Text(s.label)),
              ],
              selected: {_source},
              showSelectedIcon: false,
              onSelectionChanged: _saving
                  ? null
                  : (v) {
                      setState(() => _source = v.first);
                      _fetch();
                    },
            ),
          ),
          if (demo && _source == ImportSource.phone)
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 4, 16, 0),
              child: Text(
                'Demo: these are your phone’s real contacts, but anything you import goes into the demo’s '
                'sample books only and disappears when the demo ends.',
                style: TextStyle(fontSize: 13, color: AccnomosColors.warnText),
              ),
            ),
          if ((_note ?? '').isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 6, 16, 0),
              child: Text(_note!, style: const TextStyle(fontSize: 13, color: AccnomosColors.muted)),
            ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: Text(_error!,
                  style: const TextStyle(fontSize: 14, color: AccnomosColors.negText, fontWeight: FontWeight.w600)),
            ),
          if (_loading) const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator())),
          if (!_loading && rows != null && rows.isEmpty)
            Padding(
              padding: const EdgeInsets.all(16),
              child: Text(switch (_source) {
                ImportSource.phone => 'No contacts on this phone.',
                ImportSource.outlook => 'No Outlook contacts were found.',
                ImportSource.email => 'No one has emailed you in the last 180 days, apart from newsletters.',
              }),
            ),
          if (!_loading && rows != null && rows.isNotEmpty) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: TextField(
                decoration: const InputDecoration(
                  prefixIcon: Icon(Icons.search),
                  hintText: 'Search name, email or phone',
                ),
                onChanged: (v) => setState(() => _query = v),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(8, 4, 8, 0),
              child: Wrap(
                spacing: 4,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  TextButton(
                    onPressed: () => setState(() => _picked.addAll(_shown.map((r) => r.ref))),
                    child: const Text('Select all'),
                  ),
                  TextButton(
                    onPressed: () => setState(_picked.clear),
                    child: const Text('Clear'),
                  ),
                  PopupMenuButton<String>(
                    tooltip: 'Set the kind of every ticked row',
                    onSelected: _setAllKinds,
                    itemBuilder: (_) => const [
                      PopupMenuItem(value: 'customer', child: Text('Ticked are customers')),
                      PopupMenuItem(value: 'supplier', child: Text('Ticked are suppliers')),
                      PopupMenuItem(value: 'both', child: Text('Ticked are both')),
                    ],
                    child: const Padding(
                      padding: EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                      child: Text('Set kind…',
                          style: TextStyle(color: AccnomosColors.teal, fontWeight: FontWeight.w600)),
                    ),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Text(
                '${rows.length - existing} new · $existing already in your books · ${_chosen.length} ticked',
                style: const TextStyle(fontSize: 13, color: AccnomosColors.muted),
              ),
            ),
            Expanded(
              child: ListView.separated(
                key: const Key('import-list'),
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                itemCount: _shown.length,
                separatorBuilder: (_, _) => const SizedBox(height: 8),
                itemBuilder: (context, i) => _row(_shown[i]),
              ),
            ),
          ] else
            const Spacer(),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
              child: FilledButton(
                key: const Key('import-save'),
                onPressed: _saving || _loading || _chosen.isEmpty ? null : _save,
                style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
                child: Text(_saving ? 'Importing…' : 'Import ${_chosen.length}'),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _row(ImportCandidate r) {
    final ticked = _picked.contains(r.ref);
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AccnomosColors.border),
      ),
      padding: const EdgeInsets.fromLTRB(4, 8, 12, 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Checkbox(
            value: ticked,
            onChanged: (v) => setState(() => v == true ? _picked.add(r.ref) : _picked.remove(r.ref)),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const SizedBox(height: 10),
                Text(r.name, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
                if (r.details.isNotEmpty)
                  Text(r.details, style: const TextStyle(fontSize: 13, color: AccnomosColors.muted)),
                if (r.existing)
                  Container(
                    margin: const EdgeInsets.only(top: 4),
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(
                      color: AccnomosColors.infoTint,
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(
                      'Already in your books'
                      '${r.existingName != null && r.existingName != r.name ? ' as ${r.existingName}' : ''}'
                      '${r.match != null ? ' (${r.match})' : ''}',
                      style: const TextStyle(fontSize: 12, color: AccnomosColors.infoText, fontWeight: FontWeight.w600),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          DropdownButton<String>(
            value: r.kind,
            underline: const SizedBox.shrink(),
            items: const [
              DropdownMenuItem(value: 'customer', child: Text('Customer')),
              DropdownMenuItem(value: 'supplier', child: Text('Supplier')),
              DropdownMenuItem(value: 'both', child: Text('Both')),
            ],
            onChanged: (v) => setState(() => r.kind = v ?? r.kind),
          ),
        ],
      ),
    );
  }
}
