import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/books.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import 'new_invoice_screen.dart';

/// One job as on the web's /jobs?id=…: labour, value, materials and margin
/// worked out by the runtime (`GET /jobs/{id}/summary`), hours by person,
/// the timesheet entries, edit the job, and "Invoice these hours", which
/// opens a new invoice prefilled with the proposed lines.
class JobDetailScreen extends StatefulWidget {
  const JobDetailScreen({
    super.key,
    required this.jobId,
    this.settings,
    this.auth,
    this.account,
    this.clientFor,
  });

  final String jobId;
  final AppSettings? settings;
  final AuthService? auth;
  final Account? account;

  /// Tests inject a fake client here.
  final Future<RuntimeClient> Function()? clientFor;

  @override
  State<JobDetailScreen> createState() => _JobDetailScreenState();
}

class _JobDetailScreenState extends State<JobDetailScreen> {
  Map<String, dynamic>? _summary;
  List<Map<String, dynamic>> _entries = const [];
  bool _loading = true;
  bool _busy = false;
  String? _error;

  Future<RuntimeClient> _client() {
    final f = widget.clientFor;
    if (f != null) return f();
    return booksClient(widget.settings!, widget.auth!, widget.account);
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final c = await _client();
      final results = await Future.wait([
        c.jobSummary(widget.jobId),
        c.timesheets(jobId: widget.jobId),
      ]);
      if (!mounted) return;
      setState(() {
        _summary = results[0] as Map<String, dynamic>;
        _entries = results[1] as List<Map<String, dynamic>>;
      });
    } catch (e) {
      if (mounted) setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Map<String, dynamic> get _job =>
      _summary?['job'] is Map ? Map<String, dynamic>.from(_summary!['job'] as Map) : const {};

  Future<void> _edit() async {
    final c = await _client();
    if (!mounted) return;
    final changed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => JobEditSheet(client: c, job: _job),
    );
    if (changed == true) await _load();
  }

  Future<void> _invoiceHours() async {
    if (_busy) return;
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final c = await _client();
      final proposal = await c.jobInvoiceLines(widget.jobId);
      final lines = [
        if (proposal['lines'] is List)
          for (final l in proposal['lines'] as List)
            if (l is Map) Map<String, dynamic>.from(l),
      ];
      if (!mounted) return;
      if (lines.isEmpty) {
        final warnings = [
          if (proposal['warnings'] is List)
            for (final w in proposal['warnings'] as List) w.toString(),
        ];
        messenger.showSnackBar(SnackBar(
            duration: const Duration(seconds: 5),
            content: Text(warnings.isNotEmpty ? warnings.join(' ') : 'No unbilled billable hours on this job.')));
        return;
      }
      final settings = widget.settings ?? await AppSettings.load();
      if (!mounted) return;
      await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => NewInvoiceScreen(
          settings: settings,
          auth: widget.auth ?? AuthService(),
          account: widget.account,
          jobId: widget.jobId,
          prefillCustomerName: _summary?['customer_name']?.toString(),
          prefillCustomerId: proposal['customer_id']?.toString(),
          prefillLines: lines,
        ),
      ));
      await _load();
    } catch (e) {
      messenger.showSnackBar(SnackBar(duration: const Duration(seconds: 6), content: Text(friendly(e))));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _deleteEntry(Map<String, dynamic> e) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      await (await _client()).deleteTimesheet((e['id'] ?? '').toString());
      await _load();
    } catch (err) {
      messenger.showSnackBar(SnackBar(duration: const Duration(seconds: 6), content: Text(friendly(err))));
    }
  }

  String _hours(Object? h) {
    if (h is! num) return '—';
    return h == h.roundToDouble() ? '${h.toInt()} h' : '$h h';
  }

  int _p(Object? v) => v is num ? v.toInt() : 0;

  @override
  Widget build(BuildContext context) {
    final s = _summary;
    final name = (_job['name'] ?? 'Job').toString();
    return Scaffold(
      appBar: AppBar(
        title: Text(name),
        actions: [
          if (s != null)
            IconButton(
              icon: const Icon(Icons.edit_outlined),
              tooltip: 'Edit job',
              onPressed: _edit,
            ),
        ],
      ),
      body: _loading && s == null
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
                children: [
                  if (_error != null)
                    Text(_error!, style: const TextStyle(color: Color(0xFFA12626))),
                  if (s != null) ...[
                    Text(
                      [
                        (_job['status'] ?? '') == 'closed' ? 'Closed' : 'Open',
                        if ((s['customer_name'] ?? '').toString().isNotEmpty) s['customer_name'].toString(),
                        if ((_job['site_address'] ?? '').toString().isNotEmpty) _job['site_address'].toString(),
                      ].join(' · '),
                      style: const TextStyle(color: AccnomosColors.muted),
                    ),
                    const SizedBox(height: 12),
                    _Figures(rows: [
                      ('Hours', _hours(s['hours'])),
                      ('Unbilled', _hours(s['unbilled_hours'])),
                      ('Labour cost', gbp(_p(s['labour_cost_pence']))),
                      ('Billable value', gbp(_p(s['billable_value_pence']))),
                      ('Invoiced', gbp(_p(s['invoiced_value_pence']))),
                      ('Not yet invoiced', gbp(_p(s['unbilled_value_pence']))),
                      ('Materials', gbp(_p(s['materials_pence']))),
                      ('Margin', gbp(_p(s['margin_pence']))),
                    ]),
                    const Padding(
                      padding: EdgeInsets.only(top: 6),
                      child: Text('Worked out by code from timesheets, staff rates and approved purchases.',
                          style: TextStyle(color: AccnomosColors.muted, fontSize: 12)),
                    ),
                    for (final w in (s['warnings'] is List ? s['warnings'] as List : const []))
                      Padding(
                        padding: const EdgeInsets.only(top: 6),
                        child: Text(w.toString(), style: const TextStyle(color: Color(0xFF8A470D))),
                      ),
                    const SizedBox(height: 12),
                    FilledButton.icon(
                      icon: const Icon(Icons.request_quote_outlined),
                      label: Text(_busy ? 'Working…' : 'Invoice these hours'),
                      onPressed: _busy || _p(s['unbilled_value_pence']) == 0 && (s['unbilled_hours'] ?? 0) == 0
                          ? null
                          : _invoiceHours,
                    ),
                    const SizedBox(height: 16),
                    Text('By person', style: Theme.of(context).textTheme.titleMedium),
                    for (final b in (s['by_staff'] is List ? s['by_staff'] as List : const []))
                      if (b is Map)
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          title: Text('${b['name']}${(b['role'] ?? '').toString().isNotEmpty ? ' · ${b['role']}' : ''}'),
                          subtitle: Text('${_hours(b['hours'])} · cost ${gbp(_p(b['labour_cost_pence']))}'),
                          trailing: Text(gbp(_p(b['billable_value_pence'])),
                              style: const TextStyle(fontWeight: FontWeight.w700)),
                        ),
                    const SizedBox(height: 8),
                    Text('Timesheet entries', style: Theme.of(context).textTheme.titleMedium),
                    if (_entries.isEmpty)
                      const Text('No hours logged yet.', style: TextStyle(color: AccnomosColors.muted)),
                    for (final e in _entries)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text('${ukDate((e['date'] ?? '').toString())} · ${_hours(e['hours'])}'),
                        subtitle: Text([
                          if ((e['note'] ?? '').toString().isNotEmpty) e['note'].toString(),
                          e['billable'] == false ? 'not billable' : 'billable',
                          if (e['invoiced_in'] != null) 'invoiced in ${e['invoiced_in']}',
                        ].join(' · ')),
                        trailing: e['invoiced_in'] != null
                            ? null
                            : IconButton(
                                icon: const Icon(Icons.delete_outline),
                                tooltip: 'Delete these hours',
                                onPressed: () => _deleteEntry(e),
                              ),
                      ),
                  ],
                ],
              ),
            ),
    );
  }
}

class _Figures extends StatelessWidget {
  const _Figures({required this.rows});

  final List<(String, String)> rows;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AccnomosColors.border),
      ),
      child: Column(children: [
        for (final r in rows)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Row(children: [
              Expanded(child: Text(r.$1, style: const TextStyle(color: AccnomosColors.muted))),
              Text(r.$2,
                  style: const TextStyle(
                      fontWeight: FontWeight.w700, fontFeatures: [FontFeature.tabularFigures()])),
            ]),
          ),
      ]),
    );
  }
}

/// Add or edit a job: name, customer, site address, visit estimate, open/closed.
class JobEditSheet extends StatefulWidget {
  const JobEditSheet({super.key, required this.client, this.job = const {}});

  final RuntimeClient client;
  final Map<String, dynamic> job;

  @override
  State<JobEditSheet> createState() => _JobEditSheetState();
}

class _JobEditSheetState extends State<JobEditSheet> {
  late final _name = TextEditingController(text: (widget.job['name'] ?? '').toString());
  late final _site = TextEditingController(text: (widget.job['site_address'] ?? '').toString());
  late final _estimate = TextEditingController(
      text: widget.job['estimate_hours'] == null ? '' : widget.job['estimate_hours'].toString());
  late String? _customerId = widget.job['customer_id']?.toString();
  late bool _closed = widget.job['status'] == 'closed';
  List<Map<String, dynamic>> _customers = const [];
  bool _saving = false;
  String? _error;

  bool get _isNew => (widget.job['id'] ?? '').toString().isEmpty;

  @override
  void initState() {
    super.initState();
    widget.client.invoiceCustomers().then((rows) {
      if (mounted) setState(() => _customers = rows);
    }).catchError((_) {});
  }

  @override
  void dispose() {
    _name.dispose();
    _site.dispose();
    _estimate.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final name = _name.text.trim();
    if (name.isEmpty) {
      setState(() => _error = 'Give the job a name.');
      return;
    }
    final est = _estimate.text.trim();
    final estimate = est.isEmpty ? null : double.tryParse(est);
    if (est.isNotEmpty && (estimate == null || estimate <= 0)) {
      setState(() => _error = 'The visit estimate is hours, e.g. 2 or 1.5.');
      return;
    }
    final body = {
      'name': name,
      'customer_id': (_customerId ?? '').isEmpty ? null : _customerId,
      'site_address': _site.text.trim().isEmpty ? null : _site.text.trim(),
      'estimate_hours': estimate,
      'status': _closed ? 'closed' : 'open',
    };
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      if (_isNew) {
        await widget.client.createJob(body);
      } else {
        await widget.client.updateJob(widget.job['id'].toString(), body);
      }
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final ids = {for (final c in _customers) (c['contact_id'] ?? c['id']).toString()};
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 16, 16, 16 + MediaQuery.of(context).viewInsets.bottom),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(_isNew ? 'Add a job' : 'Edit job', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 12),
            TextField(controller: _name, decoration: const InputDecoration(labelText: 'Job name')),
            const SizedBox(height: 8),
            DropdownButtonFormField<String>(
              initialValue: ids.contains(_customerId) ? _customerId : '',
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Customer'),
              items: [
                const DropdownMenuItem(value: '', child: Text('No customer')),
                for (final c in _customers)
                  DropdownMenuItem(
                    value: (c['contact_id'] ?? c['id']).toString(),
                    child: Text((c['name'] ?? '').toString(), overflow: TextOverflow.ellipsis),
                  ),
              ],
              onChanged: (v) => setState(() => _customerId = v),
            ),
            const SizedBox(height: 8),
            TextField(controller: _site, decoration: const InputDecoration(labelText: 'Site address (optional)')),
            const SizedBox(height: 8),
            TextField(
              controller: _estimate,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Hours on site per visit (optional)'),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Job closed'),
              value: _closed,
              onChanged: (v) => setState(() => _closed = v),
            ),
            if (_error != null)
              Text(_error!, style: const TextStyle(color: Color(0xFFA12626))),
            const SizedBox(height: 8),
            FilledButton(
              onPressed: _saving ? null : _save,
              child: Text(_saving ? 'Saving…' : (_isNew ? 'Add job' : 'Save job')),
            ),
          ],
        ),
      ),
    );
  }
}

/// Staff and their rates (`/staff`): what each person costs per hour and,
/// optionally, what you charge for their time. Timesheets, pay runs and job
/// margins all use these.
class StaffScreen extends StatefulWidget {
  const StaffScreen({super.key, required this.clientFor});

  final Future<RuntimeClient> Function() clientFor;

  @override
  State<StaffScreen> createState() => _StaffScreenState();
}

class _StaffScreenState extends State<StaffScreen> {
  List<Map<String, dynamic>> _staff = const [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final rows = await (await widget.clientFor()).staff();
      if (mounted) setState(() => _staff = rows);
    } catch (e) {
      if (mounted) setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _edit([Map<String, dynamic> member = const {}]) async {
    final c = await widget.clientFor();
    if (!mounted) return;
    final changed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => StaffEditSheet(client: c, member: member),
    );
    if (changed == true) await _load();
  }

  int _p(Object? v) => v is num ? v.toInt() : 0;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Staff and rates')),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.person_add_alt_outlined),
        label: const Text('Add a person'),
        onPressed: () => _edit(),
      ),
      body: _loading && _staff.isEmpty
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
                children: [
                  if (_error != null) Text(_error!, style: const TextStyle(color: Color(0xFFA12626))),
                  if (_staff.isEmpty && _error == null)
                    const Text('No staff yet. Add the people who log hours on jobs.',
                        style: TextStyle(color: AccnomosColors.muted)),
                  for (final m in _staff)
                    Card(
                      margin: const EdgeInsets.only(bottom: 8),
                      child: ListTile(
                        title: Text((m['name'] ?? '').toString(), style: const TextStyle(fontWeight: FontWeight.w700)),
                        subtitle: Text([
                          if ((m['role'] ?? '').toString().isNotEmpty) m['role'].toString(),
                          'costs ${gbp(_p(m['hourly_rate_pence']))}/h',
                          if (m['charge_rate_pence'] is num) 'charged ${gbp(_p(m['charge_rate_pence']))}/h',
                          if (m['active'] == false) 'inactive',
                        ].join(' · ')),
                        trailing: const Icon(Icons.edit_outlined),
                        onTap: () => _edit(m),
                      ),
                    ),
                ],
              ),
            ),
    );
  }
}

/// Add or edit one person: name, role, cost per hour, charge per hour, active.
class StaffEditSheet extends StatefulWidget {
  const StaffEditSheet({super.key, required this.client, this.member = const {}});

  final RuntimeClient client;
  final Map<String, dynamic> member;

  @override
  State<StaffEditSheet> createState() => _StaffEditSheetState();
}

class _StaffEditSheetState extends State<StaffEditSheet> {
  static String _pounds(Object? p) => p is num ? (p / 100).toStringAsFixed(2) : '';

  late final _name = TextEditingController(text: (widget.member['name'] ?? '').toString());
  late final _role = TextEditingController(text: (widget.member['role'] ?? '').toString());
  late final _cost = TextEditingController(text: _pounds(widget.member['hourly_rate_pence']));
  late final _charge = TextEditingController(text: _pounds(widget.member['charge_rate_pence']));
  late bool _active = widget.member['active'] != false;
  bool _saving = false;
  String? _error;

  bool get _isNew => (widget.member['id'] ?? '').toString().isEmpty;

  @override
  void dispose() {
    _name.dispose();
    _role.dispose();
    _cost.dispose();
    _charge.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final name = _name.text.trim();
    final cost = double.tryParse(_cost.text.trim().replaceAll('£', ''));
    final chargeText = _charge.text.trim().replaceAll('£', '');
    final charge = chargeText.isEmpty ? null : double.tryParse(chargeText);
    if (name.isEmpty) return setState(() => _error = 'Add a name.');
    if (cost == null || cost < 0) return setState(() => _error = 'Cost per hour is pounds, e.g. 18.50.');
    if (chargeText.isNotEmpty && (charge == null || charge < 0)) {
      return setState(() => _error = 'Charge per hour is pounds, e.g. 45.00, or leave it empty.');
    }
    final body = {
      'name': name,
      'role': _role.text.trim(),
      'hourly_rate_pence': (cost * 100).round(),
      'charge_rate_pence': charge == null ? null : (charge * 100).round(),
      'active': _active,
    };
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      if (_isNew) {
        await widget.client.createStaff(body);
      } else {
        await widget.client.updateStaff(widget.member['id'].toString(), body);
      }
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 16, 16, 16 + MediaQuery.of(context).viewInsets.bottom),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(_isNew ? 'Add a person' : 'Edit person', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 12),
            TextField(controller: _name, decoration: const InputDecoration(labelText: 'Name')),
            const SizedBox(height: 8),
            TextField(controller: _role, decoration: const InputDecoration(labelText: 'Role (optional)')),
            const SizedBox(height: 8),
            TextField(
              controller: _cost,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Cost per hour (£)'),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _charge,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Charge per hour (£, optional)'),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Active'),
              value: _active,
              onChanged: (v) => setState(() => _active = v),
            ),
            if (_error != null) Text(_error!, style: const TextStyle(color: Color(0xFFA12626))),
            const SizedBox(height: 8),
            FilledButton(
              onPressed: _saving ? null : _save,
              child: Text(_saving ? 'Saving…' : (_isNew ? 'Add person' : 'Save')),
            ),
          ],
        ),
      ),
    );
  }
}
