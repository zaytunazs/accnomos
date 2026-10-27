import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/books.dart';
import '../services/settings.dart';
import '../theme.dart';
import 'settings_screen.dart';

/// Jobs from `GET /jobs`, plus a quick timesheet entry
/// (`POST /timesheets`) with a date picker.
class JobsScreen extends StatefulWidget {
  const JobsScreen({super.key});

  @override
  State<JobsScreen> createState() => _JobsScreenState();
}

class _JobsScreenState extends State<JobsScreen> {
  final AuthService _auth = AuthService();
  AppSettings? _settings;
  Account? _account;
  bool _authChecked = false;
  bool _loading = false;
  String? _error;
  List<Map<String, dynamic>> _rows = const [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final settings = await AppSettings.load();
    Account? account;
    try {
      account = await _auth.account();
    } catch (_) {
      account = null;
    }
    if (!mounted) return;
    setState(() {
      _settings = settings;
      _account = account;
      _authChecked = true;
    });
    if (account != null) await _reload();
  }

  Future<void> _reload() async {
    final settings = _settings;
    if (settings == null || _account == null || _loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final client = await booksClient(settings, _auth, _account);
      final rows = await client.jobs();
      if (!mounted) return;
      setState(() => _rows = rows);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          'Jobs',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        actions: [
          if (_account != null)
            IconButton(
              icon: const Icon(Icons.refresh_outlined),
              tooltip: 'Reload jobs',
              constraints:
                  const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : _reload,
            ),
        ],
      ),
      floatingActionButton: _account == null
          ? null
          : FloatingActionButton.extended(
              backgroundColor: AccnomosColors.teal,
              icon: const Icon(Icons.add_outlined),
              label: const Text('Log hours'),
              onPressed: () async {
                final messenger = ScaffoldMessenger.of(context);
                final added = await Navigator.of(context).push(
                  MaterialPageRoute(
                      builder: (_) => AddTimesheetScreen(
                            settings: _settings!,
                            auth: _auth,
                            account: _account,
                          )),
                );
                if (added != true) return;
                messenger.showSnackBar(
                  const SnackBar(
                      content:
                          Text('Timesheet entry added.')),
                );
              },
            ),
      body: !_authChecked || _loading && _rows.isEmpty && _error == null
          ? const Center(child: CircularProgressIndicator())
          : _account == null
              ? _signedOut()
              : _error != null && _rows.isEmpty
                  ? _errorView()
                  : _listView(),
    );
  }

  Widget _signedOut() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'Sign in to see your jobs.',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 12),
            FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: AccnomosColors.teal,
                minimumSize: const Size.fromHeight(48),
              ),
              onPressed: () => Navigator.of(context)
                  .push(
                    MaterialPageRoute(
                        builder: (_) =>
                            const SettingsScreen()),
                  )
                  .then((_) => _load()),
              child: const Text('Sign in'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _errorView() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(_error ?? 'Could not load jobs.',
                textAlign: TextAlign.center),
            const SizedBox(height: 12),
            FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: AccnomosColors.teal,
                minimumSize: const Size.fromHeight(48),
              ),
              onPressed: _reload,
              child: const Text('Try again'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _listView() {
    return RefreshIndicator(
      onRefresh: _reload,
      child: _rows.isEmpty && !_loading
          ? ListView(
              padding: const EdgeInsets.all(24),
              children: const [
                Center(child: Text('No jobs yet.'))
              ],
            )
          : ListView.separated(
              padding:
                  const EdgeInsets.fromLTRB(16, 8, 16, 88),
              itemCount: _rows.length,
              separatorBuilder: (_, _) =>
                  const SizedBox(height: 8),
              itemBuilder: (context, i) =>
                  _row(_rows[i]),
            ),
    );
  }

  Widget _row(Map<String, dynamic> summary) {
    final job = summary['job'];
    final name = job is Map
        ? (job['name'] ?? 'Unnamed job').toString()
        : 'Unnamed job';
    final status =
        job is Map ? (job['status'] ?? '').toString() : '';
    final customer =
        (summary['customer_name'] ?? '').toString();
    final unbilled = summary['unbilled_hours'];
    return Card(
      margin: EdgeInsets.zero,
      child: ListTile(
        minVerticalPadding: 10,
        title: Text(name,
            style:
                const TextStyle(fontWeight: FontWeight.w700)),
        subtitle: Text(
          '${status == 'closed' ? 'Closed' : 'Open'}'
          '${customer.isNotEmpty ? ' · $customer' : ''}',
          style:
              const TextStyle(color: AccnomosColors.muted),
        ),
        trailing: Text(
          unbilled == null
              ? ''
              : '${unbilled.toString()} h due',
          style: const TextStyle(
              fontWeight: FontWeight.w800, fontSize: 14),
        ),
      ),
    );
  }
}

/// Quick-add timesheet entry: staff, job, date, hours and a note.
class AddTimesheetScreen extends StatefulWidget {
  const AddTimesheetScreen({
    super.key,
    required this.settings,
    required this.auth,
    required this.account,
  });

  final AppSettings settings;
  final AuthService auth;
  final Account? account;

  @override
  State<AddTimesheetScreen> createState() =>
      _AddTimesheetState();
}

class _AddTimesheetState extends State<AddTimesheetScreen> {
  final _hours = TextEditingController();
  final _note = TextEditingController();
  List<Map<String, dynamic>> _staff = const [];
  List<Map<String, dynamic>> _jobs = const [];
  String? _staffId;
  String? _jobId;
  DateTime _date = DateTime.now();
  bool _loadingLists = true;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadLists();
  }

  @override
  void dispose() {
    _hours.dispose();
    _note.dispose();
    super.dispose();
  }

  Future<void> _loadLists() async {
    try {
      final client = await booksClient(
          widget.settings, widget.auth, widget.account);
      final staff = await client.staff();
      final jobs = await client.jobList(status: 'open');
      if (!mounted) return;
      setState(() {
        _staff = [for (final s in staff) if ((s['active'] ?? true) == true) s];
        if (_staff.isEmpty) _staff = staff;
        _jobs = jobs;
        _loadingLists = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = friendly(e);
        _loadingLists = false;
      });
    }
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _date,
      firstDate: DateTime(2020),
      lastDate: DateTime.now().add(
        const Duration(days: 1),
      ),
    );
    if (picked != null && mounted) {
      setState(() => _date = picked);
    }
  }

  Future<void> _save() async {
    final hours = double.tryParse(_hours.text.trim());
    if (_staffId == null || _staffId!.isEmpty) {
      setState(() => _error = 'Choose who did the work.');
      return;
    }
    if (_jobId == null || _jobId!.isEmpty) {
      setState(() => _error = 'Choose a job.');
      return;
    }
    if (hours == null || hours <= 0) {
      setState(
          () => _error = 'Enter the hours (above 0).');
      return;
    }
    if (_saving) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final client = await booksClient(
          widget.settings, widget.auth, widget.account);
      await client.addTimesheet({
        'staff_id': _staffId,
        'job_id': _jobId,
        'date': isoDate(_date),
        'hours': hours,
        'note': _note.text.trim(),
        'billable': true,
      });
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          'Log hours',
          style: Theme.of(context).textTheme.titleMedium,
        ),
      ),
      body: _loadingLists
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                DropdownButtonFormField<String>(
                  initialValue: _staffId,
                  decoration: const InputDecoration(
                    labelText: 'Staff',
                    border: OutlineInputBorder(),
                    filled: true,
                    fillColor: Colors.white,
                  ),
                  items: [
                    for (final s in _staff)
                      DropdownMenuItem(
                        value: (s['id'] ?? '').toString(),
                        child: Text(
                            (s['name'] ?? 'Unnamed').toString()),
                      ),
                  ],
                  onChanged: (v) =>
                      setState(() => _staffId = v),
                ),
                const SizedBox(height: 10),
                DropdownButtonFormField<String>(
                  initialValue: _jobId,
                  decoration: const InputDecoration(
                    labelText: 'Job',
                    border: OutlineInputBorder(),
                    filled: true,
                    fillColor: Colors.white,
                  ),
                  items: [
                    for (final j in _jobs)
                      DropdownMenuItem(
                        value: (j['id'] ?? '').toString(),
                        child: Text(
                            (j['name'] ?? 'Unnamed').toString()),
                      ),
                  ],
                  onChanged: (v) =>
                      setState(() => _jobId = v),
                ),
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  icon:
                      const Icon(Icons.calendar_today_outlined),
                  label: Text(ukDate(isoDate(_date))),
                  style: OutlinedButton.styleFrom(
                      minimumSize:
                          const Size.fromHeight(52)),
                  onPressed: _pickDate,
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: _hours,
                  keyboardType:
                      const TextInputType.numberWithOptions(
                          decimal: true),
                  decoration: const InputDecoration(
                    labelText: 'Hours',
                    border: OutlineInputBorder(),
                    filled: true,
                    fillColor: Colors.white,
                  ),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: _note,
                  maxLines: 3,
                  minLines: 1,
                  decoration: const InputDecoration(
                    labelText: 'Note (optional)',
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
                          color: Color(0xFF8A3F06),
                          height: 1.4)),
                ],
                const SizedBox(height: 16),
                FilledButton(
                  style: FilledButton.styleFrom(
                    backgroundColor: AccnomosColors.teal,
                    minimumSize: const Size.fromHeight(52),
                  ),
                  onPressed: _saving ? null : _save,
                  child: const Text('Save hours'),
                ),
              ],
            ),
    );
  }
}
