import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/books.dart';
import '../services/settings.dart';
import '../theme.dart';
import 'settings_screen.dart';

/// Vehicles from `GET /vehicles`, this quarter's allowance from
/// `GET /mileage/summary`, and a quick mileage entry (`POST /mileage`).
class VehiclesScreen extends StatefulWidget {
  const VehiclesScreen({super.key});

  @override
  State<VehiclesScreen> createState() => _VehiclesScreenState();
}

class _VehiclesScreenState extends State<VehiclesScreen> {
  final AuthService _auth = AuthService();
  AppSettings? _settings;
  Account? _account;
  bool _authChecked = false;
  bool _loading = false;
  String? _error;
  List<Map<String, dynamic>> _vehicles = const [];
  Map<String, dynamic>? _summary;

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
      final vehicles = await client.vehicles();
      final summary = await client.mileageSummary();
      if (!mounted) return;
      setState(() {
        _vehicles = vehicles;
        _summary = summary;
      });
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
          'Vehicles',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        actions: [
          if (_account != null)
            IconButton(
              icon: const Icon(Icons.refresh_outlined),
              tooltip: 'Reload vehicles',
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
              label: const Text('Log journey'),
              onPressed: _vehicles.isEmpty
                  ? null
                  : () async {
                      final messenger =
                          ScaffoldMessenger.of(context);
                      final added =
                          await Navigator.of(context).push(
                        MaterialPageRoute(
                            builder: (_) =>
                                AddMileageScreen(
                                  settings: _settings!,
                                  auth: _auth,
                                  account: _account,
                                  vehicles: _vehicles,
                                )),
                      );
                      if (added != true) return;
                      messenger.showSnackBar(
                        const SnackBar(
                            content:
                                Text('Journey added.')),
                      );
                      if (!mounted) return;
                      _reload();
                    },
            ),
      body: !_authChecked ||
              _loading && _vehicles.isEmpty && _error == null
          ? const Center(child: CircularProgressIndicator())
          : _account == null
              ? _signedOut()
              : _error != null && _vehicles.isEmpty
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
              'Sign in to see your vehicles.',
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
            Text(_error ?? 'Could not load vehicles.',
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
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 88),
        children: [
          _allowanceTile(),
          const SizedBox(height: 12),
          if (_vehicles.isEmpty)
            const Center(
                child: Padding(
              padding: EdgeInsets.all(16),
              child: Text('No vehicles yet.'),
            ))
          else
            for (final v in _vehicles) _vehicleCard(v),
        ],
      ),
    );
  }

  /// This quarter's allowance, worked out by the runtime.
  Widget _allowanceTile() {
    final summary = _summary;
    final quarter = summary == null
        ? null
        : currentQuarter(summary, DateTime.now());
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AccnomosColors.tealTint,
        borderRadius: BorderRadius.circular(16),
      ),
      child: quarter == null
          ? const Text(
              'Mileage allowance will show here once the summary loads.',
              style:
                  TextStyle(color: AccnomosColors.muted),
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Allowance · ${(quarter['period'] ?? '').toString()}',
                  style: const TextStyle(
                      fontWeight: FontWeight.w800,
                      color: AccnomosColors.tealDark),
                ),
                const SizedBox(height: 6),
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        gbp((quarter['allowance_pence'] ?? 0)
                            as num),
                        style: const TextStyle(
                            fontWeight: FontWeight.w800,
                            fontSize: 22,
                            color: AccnomosColors.tealDark),
                      ),
                    ),
                    Text(
                      '${(quarter['miles'] ?? 0).toString()} mi',
                      style: const TextStyle(
                          color: AccnomosColors.muted),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  '${gbp((quarter['unclaimed_pence'] ?? 0) as num)} unclaimed',
                  style: const TextStyle(
                      color: AccnomosColors.muted),
                ),
              ],
            ),
    );
  }

  Widget _vehicleCard(Map<String, dynamic> vehicle) {
    final name = (vehicle['name'] ?? 'Unnamed').toString();
    final reg = (vehicle['registration'] ?? '').toString();
    final kind = (vehicle['kind'] ?? '').toString();
    final active = (vehicle['active'] ?? true) == true;
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        minVerticalPadding: 10,
        leading: const Icon(Icons.directions_car_outlined),
        title: Text(name,
            style:
                const TextStyle(fontWeight: FontWeight.w700)),
        subtitle: Text(
          '${kind.isEmpty ? 'Vehicle' : kind[0].toUpperCase() + kind.substring(1)}'
          '${reg.isNotEmpty ? ' · $reg' : ''}'
          '${active ? '' : ' · Inactive'}',
          style:
              const TextStyle(color: AccnomosColors.muted),
        ),
      ),
    );
  }
}

/// Quick-add mileage: vehicle, date, from/to/miles, purpose and an
/// optional job.
class AddMileageScreen extends StatefulWidget {
  const AddMileageScreen({
    super.key,
    required this.settings,
    required this.auth,
    required this.account,
    required this.vehicles,
  });

  final AppSettings settings;
  final AuthService auth;
  final Account? account;
  final List<Map<String, dynamic>> vehicles;

  @override
  State<AddMileageScreen> createState() => _AddMileageState();
}

class _AddMileageState extends State<AddMileageScreen> {
  final _from = TextEditingController();
  final _to = TextEditingController();
  final _miles = TextEditingController();
  final _purpose = TextEditingController();
  List<Map<String, dynamic>> _jobs = const [];
  String? _vehicleId;
  String? _jobId;
  DateTime _date = DateTime.now();
  bool _loadingJobs = true;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final active = widget.vehicles
        .where((v) => (v['active'] ?? true) == true)
        .toList();
    final first = active.isEmpty ? widget.vehicles : active;
    if (first.isNotEmpty) {
      _vehicleId = (first.first['id'] ?? '').toString();
    }
    _loadJobs();
  }

  @override
  void dispose() {
    _from.dispose();
    _to.dispose();
    _miles.dispose();
    _purpose.dispose();
    super.dispose();
  }

  Future<void> _loadJobs() async {
    try {
      final client = await booksClient(
          widget.settings, widget.auth, widget.account);
      final jobs = await client.jobList(status: 'open');
      if (!mounted) return;
      setState(() {
        _jobs = jobs;
        _loadingJobs = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _loadingJobs = false);
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
    final miles = double.tryParse(_miles.text.trim());
    if (_vehicleId == null || _vehicleId!.isEmpty) {
      setState(() => _error = 'Choose a vehicle.');
      return;
    }
    if (miles == null || miles <= 0) {
      setState(
          () => _error = 'Enter the miles (above 0).');
      return;
    }
    if (_purpose.text.trim().isEmpty) {
      setState(
          () => _error = 'Say what the journey was for.');
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
      await client.addMileage({
        'vehicle_id': _vehicleId,
        'date': isoDate(_date),
        'from': _from.text.trim(),
        'to': _to.text.trim(),
        'miles': miles,
        'purpose': _purpose.text.trim(),
        'job_id': (_jobId == null || _jobId!.isEmpty)
            ? null
            : _jobId,
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
          'Log journey',
          style: Theme.of(context).textTheme.titleMedium,
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          DropdownButtonFormField<String>(
            initialValue: _vehicleId,
            decoration: const InputDecoration(
              labelText: 'Vehicle',
              border: OutlineInputBorder(),
              filled: true,
              fillColor: Colors.white,
            ),
            items: [
              for (final v in widget.vehicles)
                DropdownMenuItem(
                  value: (v['id'] ?? '').toString(),
                  child: Text(
                      (v['name'] ?? 'Unnamed').toString()),
                ),
            ],
            onChanged: (v) =>
                setState(() => _vehicleId = v),
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            icon: const Icon(Icons.calendar_today_outlined),
            label: Text(ukDate(isoDate(_date))),
            style: OutlinedButton.styleFrom(
                minimumSize: const Size.fromHeight(52)),
            onPressed: _pickDate,
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _from,
            decoration: const InputDecoration(
              labelText: 'From',
              border: OutlineInputBorder(),
              filled: true,
              fillColor: Colors.white,
            ),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _to,
            decoration: const InputDecoration(
              labelText: 'To',
              border: OutlineInputBorder(),
              filled: true,
              fillColor: Colors.white,
            ),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _miles,
            keyboardType:
                const TextInputType.numberWithOptions(
                    decimal: true),
            decoration: const InputDecoration(
              labelText: 'Miles',
              border: OutlineInputBorder(),
              filled: true,
              fillColor: Colors.white,
            ),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _purpose,
            decoration: const InputDecoration(
              labelText: 'Purpose',
              border: OutlineInputBorder(),
              filled: true,
              fillColor: Colors.white,
            ),
          ),
          const SizedBox(height: 10),
          DropdownButtonFormField<String>(
            initialValue: _jobId,
            decoration: const InputDecoration(
              labelText: 'Job (optional)',
              border: OutlineInputBorder(),
              filled: true,
              fillColor: Colors.white,
            ),
            items: [
              const DropdownMenuItem(
                  value: null,
                  child: Text('No job')),
              if (!_loadingJobs)
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
            onPressed: _saving ? null : _save,
            child: const Text('Save journey'),
          ),
        ],
      ),
    );
  }
}
