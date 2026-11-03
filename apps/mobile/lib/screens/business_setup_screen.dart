import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../services/business_prefs.dart';
import '../services/money.dart';
import '../services/runtime_client.dart';
import '../theme.dart';

/// Settings › Business setup: what the web's Settings edits that the phone
/// used to leave to it — the staff list (`/staff`), the day planner's
/// working hours and Home's inbox check (kept on this phone, as the web
/// keeps them in the browser), the invoice logo (`POST
/// /invoices/profile/logo`) and the mailboxes Outlook intake reads
/// (`/mail/mailboxes`).
class BusinessSetupScreen extends StatefulWidget {
  const BusinessSetupScreen({
    super.key,
    required this.clientFor,
    this.workAccount = false,
    this.pickImage,
  });

  final Future<RuntimeClient> Function() clientFor;

  /// A work or school account can link shared mailboxes.
  final bool workAccount;

  /// Picks an image's bytes and name (tests swap it); default: the gallery.
  final Future<(String, Uint8List)?> Function()? pickImage;

  @override
  State<BusinessSetupScreen> createState() => _BusinessSetupScreenState();
}

class _BusinessSetupScreenState extends State<BusinessSetupScreen> {
  List<Map<String, dynamic>> _staff = const [];
  List<Map<String, dynamic>> _mailboxes = const [];
  Map<String, dynamic>? _profile;
  BusinessPrefs _prefs = const BusinessPrefs();
  bool _loading = true;
  bool _busy = false;
  String? _note;
  String? _hoursNote;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    setState(() => _loading = true);
    final prefs = await BusinessPrefs.load();
    List<Map<String, dynamic>> staff = const [];
    List<Map<String, dynamic>> boxes = const [];
    Map<String, dynamic>? profile;
    String? problem;
    try {
      final c = await widget.clientFor();
      final r = await Future.wait<Object?>([
        c.staff().catchError((_) => <Map<String, dynamic>>[]),
        c.mailboxes().catchError((_) => <Map<String, dynamic>>[]),
        c.invoiceProfile().then<Object?>((v) => v).catchError((_) => null),
      ]);
      staff = (r[0] as List).cast<Map<String, dynamic>>();
      boxes = (r[1] as List).cast<Map<String, dynamic>>();
      profile = r[2] as Map<String, dynamic>?;
    } catch (e) {
      problem = '$e';
    }
    if (!mounted) return;
    setState(() {
      _prefs = prefs;
      _staff = staff;
      _mailboxes = boxes;
      _profile = profile;
      _loading = false;
      if (problem != null) _note = problem;
    });
  }

  Future<void> _act(Future<void> Function(RuntimeClient c) work, String done) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _note = null;
    });
    try {
      await work(await widget.clientFor());
      if (!mounted) return;
      setState(() => _note = done);
      await _reload();
    } catch (e) {
      if (mounted) setState(() => _note = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // -- Staff -------------------------------------------------------------- //

  Future<void> _editStaff(Map<String, dynamic>? member) async {
    final body = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _StaffSheet(member: member),
    );
    if (body == null) return;
    if (member == null) {
      await _act((c) => c.createStaff(body), 'Added ${body['name']}.');
    } else {
      await _act((c) => c.updateStaff('${member['id']}', {...member, ...body}), 'Saved ${body['name']}.');
    }
  }

  Widget _staffSection() {
    return _Section(
      title: 'Staff',
      intro: 'Names and rates for timesheets and job costs. No personal identifiers are kept.',
      children: [
        if (_staff.isEmpty)
          const Text('No staff yet.', style: TextStyle(color: AccnomosColors.muted)),
        for (final m in _staff)
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text('${m['name'] ?? ''}', style: const TextStyle(fontWeight: FontWeight.w700)),
            subtitle: Text([
              if ('${m['role'] ?? ''}'.isNotEmpty) '${m['role']}',
              'costs ${formatMoneyPence((m['hourly_rate_pence'] as num?) ?? 0)}/h',
              if (m['charge_rate_pence'] != null) 'charged ${formatMoneyPence(m['charge_rate_pence'] as num)}/h',
              if (m['active'] == false) 'not active',
            ].join(' · ')),
            trailing: Row(mainAxisSize: MainAxisSize.min, children: [
              IconButton(
                tooltip: 'Edit',
                icon: const Icon(Icons.edit_outlined),
                onPressed: _busy ? null : () => _editStaff(m),
              ),
              IconButton(
                tooltip: 'Remove',
                icon: const Icon(Icons.delete_outline),
                onPressed: _busy ? null : () => _act((c) => c.deleteStaff('${m['id']}'), 'Removed ${m['name']}.'),
              ),
            ]),
          ),
        OutlinedButton.icon(
          key: const Key('add-staff'),
          style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(44)),
          icon: const Icon(Icons.person_add_alt_outlined),
          label: const Text('Add a person'),
          onPressed: _busy ? null : () => _editStaff(null),
        ),
      ],
    );
  }

  // -- Working hours and inbox -------------------------------------------- //

  Future<void> _pickTime(bool start) async {
    final current = start ? _prefs.workStart : _prefs.workEnd;
    final parts = current.split(':');
    final picked = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(hour: int.parse(parts[0]), minute: int.parse(parts[1])),
    );
    if (picked == null) return;
    final hhmm = '${picked.hour.toString().padLeft(2, '0')}:${picked.minute.toString().padLeft(2, '0')}';
    await _saveHours(start ? _prefs.copyWith(workStart: hhmm) : _prefs.copyWith(workEnd: hhmm));
  }

  Future<void> _saveHours(BusinessPrefs next) async {
    final problem = BusinessPrefs.problem(next.workStart, next.workEnd);
    if (problem != null) {
      setState(() => _hoursNote = problem);
      return;
    }
    await next.save();
    if (!mounted) return;
    setState(() {
      _prefs = next;
      _hoursNote = 'Saved on this phone.';
    });
  }

  Widget _hoursSection() {
    return _Section(
      title: 'Working hours',
      intro: 'Used when you plan a day: visits, travel and lunch fit inside these hours. Saved on this phone.',
      children: [
        Row(children: [
          Expanded(
            child: OutlinedButton(
              key: const Key('work-start'),
              style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(44)),
              onPressed: () => _pickTime(true),
              child: Text('Start ${_prefs.workStart}'),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: OutlinedButton(
              key: const Key('work-end'),
              style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(44)),
              onPressed: () => _pickTime(false),
              child: Text('Finish ${_prefs.workEnd}'),
            ),
          ),
        ]),
        Row(children: [
          const Expanded(child: Text('Most visits a day')),
          IconButton(
            tooltip: 'Fewer',
            icon: const Icon(Icons.remove_circle_outline),
            onPressed: _prefs.maxVisits <= 1 ? null : () => _saveHours(_prefs.copyWith(maxVisits: _prefs.maxVisits - 1)),
          ),
          Text('${_prefs.maxVisits}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
          IconButton(
            tooltip: 'More',
            icon: const Icon(Icons.add_circle_outline),
            onPressed: _prefs.maxVisits >= 12 ? null : () => _saveHours(_prefs.copyWith(maxVisits: _prefs.maxVisits + 1)),
          ),
        ]),
        if (_hoursNote != null)
          Text(_hoursNote!, key: const Key('hours-note'),
              style: const TextStyle(color: AccnomosColors.tealDark, fontWeight: FontWeight.w600)),
        const Divider(height: 24),
        SwitchListTile(
          key: const Key('triage-on-home'),
          contentPadding: EdgeInsets.zero,
          title: const Text('Check the inbox when Home opens'),
          subtitle: const Text(
              'Home summarises the last week of business email and suggests replies. Reads previews only; nothing is sent.'),
          value: _prefs.triageOnHome,
          onChanged: (v) async {
            final next = _prefs.copyWith(triageOnHome: v);
            await next.save();
            if (mounted) setState(() => _prefs = next);
          },
        ),
      ],
    );
  }

  // -- Invoice logo ------------------------------------------------------- //

  Future<(String, Uint8List)?> _galleryImage() async {
    final file = await ImagePicker().pickImage(source: ImageSource.gallery, maxWidth: 2000, maxHeight: 2000);
    if (file == null) return null;
    return (file.name, await file.readAsBytes());
  }

  Future<void> _chooseLogo() async {
    final picked = await (widget.pickImage ?? _galleryImage)();
    if (picked == null) return;
    final (name, bytes) = picked;
    if (bytes.length > 1024 * 1024) {
      setState(() => _note = 'That picture is over 1 MB — pick a smaller one.');
      return;
    }
    await _act((c) => c.uploadInvoiceLogo(name, bytes), 'Logo saved. It prints on your invoices.');
  }

  Widget _logoSection() {
    final path = '${_profile?['logo_path'] ?? ''}';
    return _Section(
      title: 'Invoice logo',
      intro: 'A PNG or JPEG up to 1 MB, printed at the top of your invoices.',
      children: [
        Text(path.isEmpty ? 'No logo yet.' : 'Current logo: ${path.split('/').last}',
            style: const TextStyle(color: AccnomosColors.ink)),
        const SizedBox(height: 6),
        OutlinedButton.icon(
          key: const Key('choose-logo'),
          style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(44)),
          icon: const Icon(Icons.image_outlined),
          label: Text(path.isEmpty ? 'Choose a logo' : 'Change the logo'),
          onPressed: _busy ? null : _chooseLogo,
        ),
      ],
    );
  }

  // -- Mailboxes ---------------------------------------------------------- //

  Future<void> _editMailbox(Map<String, dynamic>? box) async {
    final body = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _MailboxSheet(mailbox: box),
    );
    if (body == null) return;
    if (box == null) {
      await _act((c) => c.addMailbox({...body, 'kind': 'shared'}), 'Linked ${body['address']}.');
    } else {
      await _act((c) => c.updateMailbox('${box['id']}', body), 'Saved ${box['address']}.');
    }
  }

  Widget _mailboxSection() {
    return _Section(
      title: 'Email intake',
      intro: 'The mailboxes Accnomos reads receipts and invoices from. Only addresses and settings are kept, never sign-ins.',
      children: [
        if (_mailboxes.isEmpty)
          const Text('Only your signed-in mailbox.', style: TextStyle(color: AccnomosColors.muted)),
        for (final b in _mailboxes)
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text('${b['address'] ?? 'Your mailbox'}', style: const TextStyle(fontWeight: FontWeight.w700)),
            subtitle: Text([
              b['kind'] == 'shared' ? 'Shared mailbox' : 'Mailbox',
              'folder: ${b['folder'] ?? 'all'}',
              if ((b['allow_senders'] as List?)?.isNotEmpty ?? false) 'only ${(b['allow_senders'] as List).length} senders',
              if ((b['deny_senders'] as List?)?.isNotEmpty ?? false) '${(b['deny_senders'] as List).length} senders skipped',
            ].join(' · ')),
            trailing: '${b['id'] ?? ''}'.isEmpty
                ? null
                : Row(mainAxisSize: MainAxisSize.min, children: [
                    IconButton(
                      tooltip: 'Change',
                      icon: const Icon(Icons.edit_outlined),
                      onPressed: _busy ? null : () => _editMailbox(b),
                    ),
                    IconButton(
                      tooltip: 'Remove',
                      icon: const Icon(Icons.link_off_outlined),
                      onPressed: _busy
                          ? null
                          : () => _act((c) => c.removeMailbox('${b['id']}'),
                              'Removed ${b['address']}. What it already copied stays in your books.'),
                    ),
                  ]),
          ),
        if (widget.workAccount)
          OutlinedButton.icon(
            key: const Key('add-mailbox'),
            style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(44)),
            icon: const Icon(Icons.add_outlined),
            label: const Text('Link a shared mailbox'),
            onPressed: _busy ? null : () => _editMailbox(null),
          )
        else
          const Text(
            'Another Microsoft mailbox is linked by signing in to it on the web, where its sign-in stays.',
            style: TextStyle(color: AccnomosColors.muted, fontSize: 12, height: 1.4),
          ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(title: const Text('Business setup')),
      body: _loading && _profile == null && _staff.isEmpty
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                // The outcome of the last change stays in view above the list,
                // however far down the change was made.
                if (_note != null)
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                    color: AccnomosColors.tealTint,
                    child: Semantics(
                      liveRegion: true,
                      child: Text(_note!, key: const Key('setup-note'),
                          style: const TextStyle(color: AccnomosColors.tealDark, height: 1.4)),
                    ),
                  ),
                Expanded(
                  child: RefreshIndicator(
                    onRefresh: _reload,
                    child: ListView(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
                      children: [
                        _staffSection(),
                        _hoursSection(),
                        _logoSection(),
                        _mailboxSection(),
                      ],
                    ),
                  ),
                ),
              ],
            ),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.intro, required this.children});
  final String title;
  final String intro;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      // A Material (not a decorated box) so the ListTiles inside paint their ink.
      child: Material(
        color: Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: const BorderSide(color: AccnomosColors.border),
        ),
        child: Padding(
          padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(title, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
          const SizedBox(height: 4),
          Text(intro, style: const TextStyle(color: AccnomosColors.muted, fontSize: 13, height: 1.4)),
          const SizedBox(height: 8),
          ...children,
        ],
      ),
        ),
      ),
    );
  }
}

int? _pence(String text) {
  final t = text.trim().replaceAll('£', '').replaceAll(',', '');
  if (t.isEmpty) return null;
  final v = double.tryParse(t);
  return v == null || v < 0 ? null : (v * 100).round();
}

String _pounds(Object? pence) => pence is num ? (pence / 100).toStringAsFixed(2) : '';

class _StaffSheet extends StatefulWidget {
  const _StaffSheet({this.member});
  final Map<String, dynamic>? member;

  @override
  State<_StaffSheet> createState() => _StaffSheetState();
}

class _StaffSheetState extends State<_StaffSheet> {
  late final _name = TextEditingController(text: '${widget.member?['name'] ?? ''}');
  late final _role = TextEditingController(text: '${widget.member?['role'] ?? ''}');
  late final _cost = TextEditingController(text: _pounds(widget.member?['hourly_rate_pence']));
  late final _charge = TextEditingController(text: _pounds(widget.member?['charge_rate_pence']));
  late bool _active = widget.member?['active'] != false;
  String? _error;

  @override
  void dispose() {
    for (final c in [_name, _role, _cost, _charge]) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.of(context).viewInsets.bottom),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(widget.member == null ? 'Add a person' : 'Edit ${widget.member!['name']}',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(height: 12),
            TextField(controller: _name, decoration: const InputDecoration(labelText: 'Name')),
            const SizedBox(height: 10),
            TextField(controller: _role, decoration: const InputDecoration(labelText: 'Role (optional)')),
            const SizedBox(height: 10),
            TextField(
              controller: _cost,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'What an hour costs you (£)'),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _charge,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'What you charge customers an hour (£, optional)'),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Active'),
              value: _active,
              onChanged: (v) => setState(() => _active = v),
            ),
            if (_error != null) Text(_error!, style: const TextStyle(color: Color(0xFF8A3F06))),
            const SizedBox(height: 8),
            FilledButton(
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
              onPressed: () {
                final cost = _pence(_cost.text);
                if (_name.text.trim().isEmpty) {
                  setState(() => _error = 'Give the person a name.');
                  return;
                }
                if (cost == null) {
                  setState(() => _error = 'Enter what an hour costs, e.g. 18.50.');
                  return;
                }
                Navigator.pop(context, {
                  'name': _name.text.trim(),
                  'role': _role.text.trim(),
                  'hourly_rate_pence': cost,
                  'charge_rate_pence': _pence(_charge.text),
                  'active': _active,
                });
              },
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
  }
}

class _MailboxSheet extends StatefulWidget {
  const _MailboxSheet({this.mailbox});
  final Map<String, dynamic>? mailbox;

  @override
  State<_MailboxSheet> createState() => _MailboxSheetState();
}

class _MailboxSheetState extends State<_MailboxSheet> {
  late final _address = TextEditingController(text: '${widget.mailbox?['address'] ?? ''}');
  late final _folder = TextEditingController(text: '${widget.mailbox?['folder'] ?? 'all'}');
  late final _allow = TextEditingController(text: ((widget.mailbox?['allow_senders'] as List?) ?? const []).join(', '));
  late final _deny = TextEditingController(text: ((widget.mailbox?['deny_senders'] as List?) ?? const []).join(', '));
  String? _error;

  @override
  void dispose() {
    for (final c in [_address, _folder, _allow, _deny]) {
      c.dispose();
    }
    super.dispose();
  }

  static List<String> _list(String text) =>
      [for (final s in text.split(RegExp(r'[,\s]+'))) if (s.trim().isNotEmpty) s.trim()];

  @override
  Widget build(BuildContext context) {
    final adding = widget.mailbox == null;
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.of(context).viewInsets.bottom),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(adding ? 'Link a shared mailbox' : 'Change ${widget.mailbox!['address']}',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(height: 12),
            if (adding) ...[
              TextField(
                controller: _address,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(labelText: 'Shared mailbox address, e.g. invoices@yourfirm.co.uk'),
              ),
              const SizedBox(height: 10),
            ],
            TextField(controller: _folder, decoration: const InputDecoration(labelText: 'Folder ("all" for every folder)')),
            const SizedBox(height: 10),
            TextField(controller: _allow, decoration: const InputDecoration(labelText: 'Only these senders (optional, comma-separated)')),
            const SizedBox(height: 10),
            TextField(controller: _deny, decoration: const InputDecoration(labelText: 'Skip these senders (optional)')),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(_error!, style: const TextStyle(color: Color(0xFF8A3F06))),
            ],
            const SizedBox(height: 12),
            FilledButton(
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
              onPressed: () {
                if (adding && !_address.text.contains('@')) {
                  setState(() => _error = 'Type the mailbox address.');
                  return;
                }
                Navigator.pop(context, {
                  if (adding) 'address': _address.text.trim(),
                  'folder': _folder.text.trim().isEmpty ? 'all' : _folder.text.trim(),
                  'allow_senders': _list(_allow.text),
                  'deny_senders': _list(_deny.text),
                });
              },
              child: Text(adding ? 'Link mailbox' : 'Save'),
            ),
          ],
        ),
      ),
    );
  }
}
