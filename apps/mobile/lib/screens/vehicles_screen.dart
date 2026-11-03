import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/books.dart';
import '../services/settings.dart';
import '../theme.dart';
import 'settings_screen.dart';

/// Vehicles (`/vehicles`: add, edit, delete or mark inactive), the mileage
/// log for the tax year (`/mileage`: add, edit, delete journeys), the
/// allowance worked out by the runtime (`GET /mileage/summary`), and the
/// quarter's claim as a proposal in Review (`POST /mileage/propose-allowance`)
/// — the same routes and rules as the web's Vehicles page.
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
  List<Map<String, dynamic>> _journeys = const [];
  Map<String, dynamic>? _summary;
  String? _busy;
  String? _note;

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
      List<Map<String, dynamic>> journeys = const [];
      try {
        journeys = await client.mileage();
      } catch (_) {}
      if (!mounted) return;
      setState(() {
        _vehicles = vehicles;
        _summary = summary;
        _journeys = journeys;
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
        title: Text(
          'Vehicles',
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
    final journeys = [..._journeys]
      ..sort((a, b) => '${b['date'] ?? ''}'.compareTo('${a['date'] ?? ''}'));
    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 88),
        children: [
          _allowanceTile(),
          if (_note != null) ...[
            const SizedBox(height: 8),
            Text(_note!, style: const TextStyle(color: AccnomosColors.ink, height: 1.4)),
          ],
          const SizedBox(height: 16),
          Row(
            children: [
              const Expanded(
                child: Text('Vehicles',
                    style: TextStyle(fontWeight: FontWeight.w700, fontSize: 18)),
              ),
              TextButton.icon(
                icon: const Icon(Icons.add_outlined),
                label: const Text('Add vehicle'),
                onPressed: _busy != null ? null : () => _editVehicle(null),
              ),
            ],
          ),
          if (_vehicles.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: Text('No vehicles yet. Add one to start logging journeys.',
                  style: TextStyle(color: AccnomosColors.muted)),
            )
          else
            for (final v in _vehicles) _vehicleCard(v),
          const SizedBox(height: 16),
          Text('Journeys this tax year (${journeys.length})',
              style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 18)),
          const SizedBox(height: 4),
          if (_summary?['locked_until'] != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text(
                'Mileage up to ${ukDate('${_summary!['locked_until']}')} has been claimed, so earlier journeys can\'t be changed (undo the claim in Review first).',
                style: const TextStyle(color: AccnomosColors.muted, height: 1.4),
              ),
            ),
          if (journeys.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: Text('No journeys logged yet.',
                  style: TextStyle(color: AccnomosColors.muted)),
            )
          else
            for (final j in journeys) _journeyCard(j),
        ],
      ),
    );
  }

  bool _locked(Map<String, dynamic> j) {
    final until = _summary?['locked_until'];
    if (until == null) return false;
    return '${j['date'] ?? ''}'.compareTo('$until') < 0;
  }

  String _vehicleName(Object? id) {
    for (final v in _vehicles) {
      if (v['id'] == id) return (v['name'] ?? 'Vehicle').toString();
    }
    return 'Vehicle';
  }

  Widget _journeyCard(Map<String, dynamic> j) {
    final from = (j['from'] ?? '').toString();
    final to = (j['to'] ?? '').toString();
    final route = [from, to].where((x) => x.isNotEmpty).join(' → ');
    final locked = _locked(j);
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        minVerticalPadding: 10,
        title: Text('${ukDate('${j['date'] ?? ''}')} · ${milesText(j['miles'])} mi',
            style: const TextStyle(fontWeight: FontWeight.w700)),
        subtitle: Text(
          [
            (j['purpose'] ?? '').toString(),
            if (route.isNotEmpty) route,
            _vehicleName(j['vehicle_id']),
            if (locked) 'Claimed',
          ].where((x) => x.isNotEmpty).join(' · '),
          style: const TextStyle(color: AccnomosColors.muted),
        ),
        trailing: locked ? const Icon(Icons.lock_outline, size: 20) : const Icon(Icons.edit_outlined, size: 20),
        onTap: locked || _busy != null ? null : () => _editJourney(j),
      ),
    );
  }

  Future<void> _editJourney(Map<String, dynamic> j) async {
    final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(
      builder: (_) => AddMileageScreen(
        settings: _settings!,
        auth: _auth,
        account: _account,
        vehicles: _vehicles,
        journey: j,
      ),
    ));
    if (changed == true && mounted) _reload();
  }

  Future<void> _editVehicle(Map<String, dynamic>? vehicle) async {
    final changed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => VehicleSheet(
        vehicle: vehicle,
        save: (body) async {
          final client = await booksClient(_settings!, _auth, _account);
          if (vehicle == null) {
            await client.addVehicle(body);
          } else {
            await client.updateVehicle('${vehicle['id']}', body);
          }
        },
        delete: vehicle == null
            ? null
            : () async {
                final client = await booksClient(_settings!, _auth, _account);
                await client.deleteVehicle('${vehicle['id']}');
              },
      ),
    );
    if (changed == true && mounted) _reload();
  }

  Future<void> _claim(String period) async {
    if (_busy != null) return;
    setState(() {
      _busy = 'claim-$period';
      _note = null;
    });
    try {
      final client = await booksClient(_settings!, _auth, _account);
      final r = await client.proposeAllowance(period: period);
      final created = r['created'] == true;
      final p = r['proposal'];
      num? pence;
      if (p is Map && p['extracted'] is Map) {
        final total = num.tryParse('${(p['extracted'] as Map)['gross_total'] ?? ''}');
        if (total != null) pence = (total * 100).round();
      }
      final amount = pence == null ? '' : ' for ${gbp(pence)}';
      if (!mounted) return;
      setState(() => _note = created
          ? '$period mileage claim$amount is waiting in Review for you to approve.'
          : '$period mileage claim${pence == null ? '' : ' (${gbp(pence)})'} is already waiting in Review, brought up to date.');
      await _reload();
    } catch (e) {
      if (!mounted) return;
      setState(() => _note = friendly(e));
    } finally {
      if (mounted) setState(() => _busy = null);
    }
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
                      '${milesText(quarter['miles'])} mi',
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
                if ((quarter['waiting_claim_id'] ?? '').toString().isNotEmpty) ...[
                  const SizedBox(height: 8),
                  const Text('A claim for this quarter is waiting in Review.',
                      style: TextStyle(color: AccnomosColors.tealDark, fontWeight: FontWeight.w600)),
                ] else if (((quarter['unclaimed_pence'] ?? 0) as num) > 0) ...[
                  const SizedBox(height: 8),
                  FilledButton(
                    style: FilledButton.styleFrom(
                      backgroundColor: AccnomosColors.teal,
                      minimumSize: const Size.fromHeight(44),
                    ),
                    onPressed: _busy != null ? null : () => _claim('${quarter['period']}'),
                    child: Text(_busy == 'claim-${quarter['period']}'
                        ? 'Working out your claim…'
                        : "Claim this quarter's mileage"),
                  ),
                  const SizedBox(height: 4),
                  const Text('The claim goes to Review; nothing is posted until you approve it.',
                      style: TextStyle(color: AccnomosColors.muted, fontSize: 13)),
                ],
                if (summary != null) ...[
                  const SizedBox(height: 8),
                  Text(
                    yearLine(summary),
                    style: const TextStyle(
                        color: AccnomosColors.ink, fontWeight: FontWeight.w600),
                  ),
                ],
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
          '${(vehicle['owned_by'] ?? '') == 'personal' ? ' · Own vehicle' : (vehicle['owned_by'] ?? '') == 'business' ? ' · Business vehicle' : ''}'
          '${active ? '' : ' · Inactive'}',
          style:
              const TextStyle(color: AccnomosColors.muted),
        ),
        trailing: const Icon(Icons.edit_outlined, size: 20),
        onTap: _busy != null ? null : () => _editVehicle(vehicle),
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
    this.journey,
  });

  final AppSettings settings;
  final AuthService auth;
  final Account? account;
  final List<Map<String, dynamic>> vehicles;

  /// An existing journey to edit (or delete); null to add one.
  final Map<String, dynamic>? journey;

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
    final j = widget.journey;
    if (j != null) {
      _vehicleId = (j['vehicle_id'] ?? _vehicleId).toString();
      _from.text = (j['from'] ?? '').toString();
      _to.text = (j['to'] ?? '').toString();
      _miles.text = milesText(j['miles']);
      _purpose.text = (j['purpose'] ?? '').toString();
      final job = (j['job_id'] ?? '').toString();
      _jobId = job.isEmpty ? null : job;
      _date = DateTime.tryParse('${j['date'] ?? ''}') ?? _date;
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
      final body = {
        'vehicle_id': _vehicleId,
        'date': isoDate(_date),
        'from': _from.text.trim(),
        'to': _to.text.trim(),
        'miles': miles,
        'purpose': _purpose.text.trim(),
        'job_id': (_jobId == null || _jobId!.isEmpty)
            ? null
            : _jobId,
      };
      final existing = widget.journey;
      if (existing == null) {
        await client.addMileage(body);
      } else {
        await client.updateMileage('${existing['id']}', body);
      }
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _delete() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Delete this journey?'),
        content: const Text('It is removed from the mileage log. Claimed journeys cannot be deleted.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Keep')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Delete')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final client = await booksClient(widget.settings, widget.auth, widget.account);
      await client.deleteMileage('${widget.journey!['id']}');
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
        title: Text(widget.journey == null ? 'Log journey' : 'Edit journey'),
        actions: [
          if (widget.journey != null)
            IconButton(
              icon: const Icon(Icons.delete_outline),
              tooltip: 'Delete journey',
              onPressed: _saving ? null : _delete,
            ),
        ],
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
            child: Text(widget.journey == null ? 'Save journey' : 'Save changes'),
          ),
        ],
      ),
    );
  }
}

/// "12.5", "40" — miles without a trailing ".0".
String milesText(Object? miles) {
  final n = num.tryParse('${miles ?? 0}') ?? 0;
  return n == n.roundToDouble() ? n.round().toString() : n.toStringAsFixed(1);
}

/// The whole tax year, so a quarter with no journeys yet never reads as if
/// the books had none: "Tax year 2026-27 so far: £123.30 · 274 mi".
String yearLine(Map<String, dynamic> summary) {
  var miles = 0.0;
  final quarters = summary['quarters'];
  if (quarters is List) {
    for (final q in quarters) {
      if (q is Map) miles += num.tryParse('${q['miles'] ?? 0}')?.toDouble() ?? 0;
    }
  }
  final pence = (summary['allowance_pence'] as num?) ?? 0;
  final year = (summary['tax_year'] ?? '').toString();
  return 'Tax year${year.isEmpty ? '' : ' $year'} so far: '
      '${gbp(pence)} · ${milesText(miles)} mi';
}

/// Add or edit a vehicle: name, registration, kind and who owns it (the
/// allowance applies to your own vehicle; a business vehicle's costs are its
/// receipts). Delete only works for a vehicle with no journeys or receipts;
/// otherwise mark it inactive.
class VehicleSheet extends StatefulWidget {
  const VehicleSheet({super.key, this.vehicle, required this.save, this.delete});

  final Map<String, dynamic>? vehicle;
  final Future<void> Function(Map<String, dynamic> body) save;
  final Future<void> Function()? delete;

  @override
  State<VehicleSheet> createState() => _VehicleSheetState();
}

class _VehicleSheetState extends State<VehicleSheet> {
  final _name = TextEditingController();
  final _reg = TextEditingController();
  String _kind = 'car';
  String _owned = 'personal';
  bool _active = true;
  bool _saving = false;
  String? _error;

  static const kinds = {'car': 'Car', 'van': 'Van', 'motorcycle': 'Motorcycle', 'bicycle': 'Bicycle'};

  @override
  void initState() {
    super.initState();
    final v = widget.vehicle;
    if (v != null) {
      _name.text = (v['name'] ?? '').toString();
      _reg.text = (v['registration'] ?? '').toString();
      _kind = kinds.containsKey(v['kind']) ? '${v['kind']}' : 'car';
      _owned = v['owned_by'] == 'business' ? 'business' : 'personal';
      _active = (v['active'] ?? true) == true;
    }
  }

  @override
  void dispose() {
    _name.dispose();
    _reg.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() work) async {
    if (_saving) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await work();
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final editing = widget.vehicle != null;
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.of(context).viewInsets.bottom),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(editing ? 'Edit vehicle' : 'Add a vehicle',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(height: 12),
            TextField(
              controller: _name,
              decoration: const InputDecoration(labelText: 'Name, e.g. "Ford Transit"'),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _reg,
              textCapitalization: TextCapitalization.characters,
              decoration: const InputDecoration(labelText: 'Registration (optional)'),
            ),
            const SizedBox(height: 10),
            DropdownButtonFormField<String>(
              initialValue: _kind,
              decoration: const InputDecoration(labelText: 'Kind'),
              items: [for (final e in kinds.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
              onChanged: (v) => setState(() => _kind = v ?? 'car'),
            ),
            const SizedBox(height: 10),
            DropdownButtonFormField<String>(
              initialValue: _owned,
              decoration: const InputDecoration(labelText: 'Who owns it'),
              items: const [
                DropdownMenuItem(value: 'personal', child: Text('My own vehicle (claim the mileage allowance)')),
                DropdownMenuItem(value: 'business', child: Text('The business (its costs are its receipts)')),
              ],
              isExpanded: true,
              onChanged: (v) => setState(() => _owned = v ?? 'personal'),
            ),
            if (editing)
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('In use'),
                subtitle: const Text('Turn off to hide it from new journeys'),
                value: _active,
                onChanged: (v) => setState(() => _active = v),
              ),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(_error!, style: const TextStyle(color: Color(0xFF8A3F06), height: 1.4)),
            ],
            const SizedBox(height: 12),
            FilledButton(
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
              onPressed: _saving
                  ? null
                  : () {
                      if (_name.text.trim().isEmpty) {
                        setState(() => _error = 'Give the vehicle a name.');
                        return;
                      }
                      final reg = _reg.text.trim().toUpperCase();
                      final body = <String, dynamic>{
                        'name': _name.text.trim(),
                        'registration': reg.isEmpty ? null : reg,
                        'kind': _kind,
                        'owned_by': _owned,
                        if (editing) 'active': _active,
                      };
                      _run(() => widget.save(body));
                    },
              child: Text(editing ? 'Save vehicle' : 'Add vehicle'),
            ),
            if (widget.delete != null) ...[
              const SizedBox(height: 8),
              TextButton(
                onPressed: _saving ? null : () => _run(widget.delete!),
                child: const Text('Delete vehicle'),
              ),
              const Text(
                'Only a vehicle with no journeys and no receipts can be deleted; otherwise turn off "In use".',
                style: TextStyle(color: AccnomosColors.muted, fontSize: 13),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
