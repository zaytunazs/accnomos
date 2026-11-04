import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/calendar.dart';
import '../services/auth.dart';
import '../services/books.dart' show booksClient, isoDate;
import '../services/books_events.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/calendar_sync.dart';

/// Calendar, as the web's /calendar: the next two weeks grouped by day (an
/// "Added by Accnomos" chip on the events this app wrote), "+ Add an event"
/// with a clash check before anything is written, Remove with a confirm, and
/// the "Add all deadlines to my calendar automatically" switch. The calendar
/// scope is asked for when this screen opens, never at sign-in; in a demo it
/// is the demo's own calendar and nothing reaches Microsoft.
class CalendarScreen extends StatefulWidget {
  const CalendarScreen({super.key, this.read, this.write, this.today});

  /// Tests: the sign-in client and the calendar-scoped client.
  final ClientFor? read;
  final ClientFor? write;

  /// Tests: the first day shown.
  final DateTime? today;

  /// The summary link for this screen (Home's summary may point here).
  static const route = '/calendar';

  @override
  State<CalendarScreen> createState() => _CalendarScreenState();
}

class _CalendarScreenState extends State<CalendarScreen> {
  final AuthService _auth = AuthService();
  ClientFor? _read;
  ClientFor? _write;
  DeadlineSync? _sync;
  bool _signedOut = false;
  bool _loading = true;
  String? _error;
  String? _notice;
  List<CalendarEvent> _events = const [];
  List<CalendarClashPair> _clashes = const [];

  DateTime get _today {
    final t = widget.today ?? DateTime.now();
    return DateTime(t.year, t.month, t.day);
  }

  @override
  void initState() {
    super.initState();
    _start();
  }

  @override
  void dispose() {
    _sync?.removeListener(_onSynced);
    _sync?.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    var read = widget.read;
    var write = widget.write;
    if (read == null || write == null) {
      final settings = await AppSettings.load();
      Account? account;
      try {
        account = await _auth.account();
      } catch (_) {
        account = null;
      }
      if (account == null) {
        if (mounted) {
          setState(() {
            _signedOut = true;
            _loading = false;
          });
        }
        return;
      }
      read ??= () => booksClient(settings, _auth, account);
      write ??= () => calendarClient(settings, _auth, account);
    }
    if (!mounted) return;
    final sync = DeadlineSync(read: read, write: write)..addListener(_onSynced);
    setState(() {
      _read = read;
      _write = write;
      _sync = sync;
    });
    sync.load();
    await _reload();
  }

  int _syncedAt = 0;

  /// A deadline sync added events: show them.
  void _onSynced() {
    final s = _sync;
    if (s == null || s.busy) return;
    if (s.syncs != _syncedAt) {
      _syncedAt = s.syncs;
      _reload(quiet: true);
    }
  }

  Future<void> _reload({bool quiet = false}) async {
    final write = _write;
    if (write == null) return;
    if (!quiet) setState(() => _loading = true);
    try {
      final client = await write();
      final start = isoDate(_today);
      final end = isoDate(_today.add(const Duration(days: 13)));
      final events = await client.calendarEvents(start: start, end: end);
      List<CalendarClashPair> clashes = const [];
      try {
        clashes = await client.calendarConflicts(start: start, end: end);
      } catch (_) {
        // The list still shows; clashes are a nicety.
      }
      if (!mounted) return;
      setState(() {
        _events = events;
        _clashes = clashes;
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _add() async {
    final write = _write;
    if (write == null) return;
    final added = await showModalBottomSheet<CalendarEvent>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => AddEventSheet(write: write, day: _today),
    );
    if (added == null || !mounted) return;
    BooksEvents.bump();
    setState(() => _notice = "Added '${added.subject}' to your calendar.");
    await _reload(quiet: true);
  }

  Future<void> _remove(CalendarEvent e) async {
    final write = _write;
    if (write == null) return;
    final yes = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Remove it?'),
        content: Text("Remove '${e.subject}' (${dayHeading(e.day)}, ${e.when}) from your calendar?"),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
          FilledButton(
            key: const Key('confirm-remove'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Yes, remove'),
          ),
        ],
      ),
    );
    if (yes != true || !mounted) return;
    try {
      await (await write()).removeCalendarEvent(e.id);
      if (!mounted) return;
      setState(() {
        _events = [for (final x in _events) if (x.id != e.id) x];
        _notice = "Removed '${e.subject}'.";
      });
    } catch (err) {
      if (mounted) setState(() => _notice = err.toString().replaceFirst('Exception: ', ''));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(title: const Text('Calendar')),
      floatingActionButton: _write == null
          ? null
          : FloatingActionButton.extended(
              key: const Key('calendar-add'),
              onPressed: _add,
              backgroundColor: AccnomosColors.teal,
              foregroundColor: Colors.white,
              icon: const Icon(Icons.add),
              label: const Text('Add an event'),
            ),
      body: _signedOut
          ? const Padding(
              padding: EdgeInsets.all(24),
              child: Text('Sign in with Microsoft in Settings to see your calendar here.',
                  style: TextStyle(color: AccnomosColors.muted, height: 1.4)),
            )
          : RefreshIndicator(
              onRefresh: _reload,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
                children: [
                  const Text('The next two weeks',
                      style: TextStyle(color: AccnomosColors.muted, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 8),
                  if (_notice != null) ...[
                    Text(_notice!, key: const Key('calendar-notice'),
                        style: const TextStyle(color: AccnomosColors.tealDark, fontWeight: FontWeight.w600)),
                    const SizedBox(height: 8),
                  ],
                  if (_clashes.isNotEmpty) ...[
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: const Color(0xFFFFF4E5),
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: const Color(0xFFF2C38B)),
                      ),
                      child: Text(
                        [for (final c in _clashes) "'${c.a.subject}' and '${c.b.subject}' overlap on ${dayHeading(isoDay(c.a.start))}."]
                            .join('\n'),
                        style: const TextStyle(color: Color(0xFF8A3F06), height: 1.4),
                      ),
                    ),
                    const SizedBox(height: 8),
                  ],
                  if (_loading)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 24),
                      child: Center(child: CircularProgressIndicator()),
                    )
                  else if (_error != null)
                    Text('Could not load your calendar: $_error',
                        style: const TextStyle(color: AccnomosColors.muted, height: 1.4))
                  else if (_events.isEmpty)
                    const Text('Nothing in the next two weeks.',
                        style: TextStyle(color: AccnomosColors.muted))
                  else
                    ..._days(),
                  const SizedBox(height: 16),
                  if (_sync != null) CalendarSyncPanel(sync: _sync!),
                ],
              ),
            ),
    );
  }

  List<Widget> _days() {
    final byDay = <String, List<CalendarEvent>>{};
    for (final e in _events) {
      byDay.putIfAbsent(e.day, () => []).add(e);
    }
    final days = byDay.keys.toList()..sort();
    return [
      for (final day in days) ...[
        Padding(
          padding: const EdgeInsets.only(top: 8, bottom: 6),
          child: Text(dayHeading(day),
              style: const TextStyle(fontWeight: FontWeight.w800, color: AccnomosColors.ink)),
        ),
        for (final e in byDay[day]!) _eventCard(e),
      ],
    ];
  }

  Widget _eventCard(CalendarEvent e) {
    return Container(
      key: Key('event-${e.id}'),
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.fromLTRB(12, 10, 4, 10),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AccnomosColors.border),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 92,
            child: Text(e.when,
                style: const TextStyle(color: AccnomosColors.muted, fontWeight: FontWeight.w600, fontSize: 13)),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(e.subject, style: const TextStyle(fontWeight: FontWeight.w700, color: AccnomosColors.ink)),
                if (e.location != null)
                  Text(e.location!, style: const TextStyle(color: AccnomosColors.muted, fontSize: 13)),
                if (e.accnomos)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: AccnomosColors.tealTint,
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: const Text('Added by Accnomos',
                          style: TextStyle(color: AccnomosColors.tealDark, fontSize: 12, fontWeight: FontWeight.w700)),
                    ),
                  ),
              ],
            ),
          ),
          IconButton(
            key: Key('remove-${e.id}'),
            tooltip: 'Remove ${e.subject}',
            constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
            icon: const Icon(Icons.delete_outline),
            onPressed: () => _remove(e),
          ),
        ],
      ),
    );
  }
}

/// "+ Add an event": title, day, all day or a time, place. Checks the
/// calendar first; a clash says "Clashes with 'X' 09:00–10:00" and offers Add
/// anyway or Cancel. Pops the event once added.
class AddEventSheet extends StatefulWidget {
  const AddEventSheet({super.key, required this.write, required this.day});

  final ClientFor write;
  final DateTime day;

  @override
  State<AddEventSheet> createState() => _AddEventSheetState();
}

class _AddEventSheetState extends State<AddEventSheet> {
  final _title = TextEditingController();
  final _location = TextEditingController();
  late DateTime _day = widget.day;
  bool _allDay = false;
  TimeOfDay _from = const TimeOfDay(hour: 9, minute: 0);
  TimeOfDay _to = const TimeOfDay(hour: 10, minute: 0);
  bool _busy = false;
  String? _error;
  List<CalendarClash>? _clashes; // non-null: asked "Add anyway?"

  @override
  void dispose() {
    _title.dispose();
    _location.dispose();
    super.dispose();
  }

  static String _hm(TimeOfDay t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  Map<String, Object?> _event() {
    final day = isoDate(_day);
    final place = _location.text.trim();
    return {
      'subject': _title.text.trim(),
      'start': _allDay ? day : '${day}T${_hm(_from)}',
      'end': _allDay ? day : '${day}T${_hm(_to)}',
      'all_day': _allDay,
      if (place.isNotEmpty) 'location': place,
    };
  }

  Future<void> _submit({bool anyway = false}) async {
    if (_title.text.trim().isEmpty) {
      setState(() => _error = 'Give it a title.');
      return;
    }
    if (!_allDay && (_to.hour * 60 + _to.minute) <= (_from.hour * 60 + _from.minute)) {
      setState(() => _error = 'The end is before the start.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final client = await widget.write();
      if (!anyway) {
        final clashes = await client.checkCalendarEvent(_event());
        if (clashes.isNotEmpty) {
          if (mounted) setState(() => _clashes = clashes);
          return;
        }
      }
      final made = await client.addCalendarEvent(_event(), allowConflict: anyway);
      if (mounted) Navigator.of(context).pop(made);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _pickDay() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _day,
      firstDate: widget.day.subtract(const Duration(days: 365)),
      lastDate: widget.day.add(const Duration(days: 730)),
    );
    if (picked != null) setState(() => _day = picked);
  }

  Future<void> _pickTime(bool from) async {
    final picked = await showTimePicker(context: context, initialTime: from ? _from : _to);
    if (picked == null) return;
    setState(() {
      if (from) {
        _from = picked;
        if (_to.hour * 60 + _to.minute <= picked.hour * 60 + picked.minute) {
          _to = TimeOfDay(hour: (picked.hour + 1) % 24, minute: picked.minute);
        }
      } else {
        _to = picked;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final clashes = _clashes;
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.of(context).viewInsets.bottom),
      child: SingleChildScrollView(
        child: Column(
          key: const Key('add-event-sheet'),
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Add an event', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 12),
            TextField(
              key: const Key('event-title'),
              controller: _title,
              enabled: clashes == null,
              maxLength: 120,
              decoration: const InputDecoration(labelText: 'Title'),
            ),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    key: const Key('event-day'),
                    style: OutlinedButton.styleFrom(minimumSize: const Size(48, 48)),
                    onPressed: clashes == null ? _pickDay : null,
                    icon: const Icon(Icons.event_outlined),
                    label: Text(dayHeading(isoDate(_day))),
                  ),
                ),
              ],
            ),
            SwitchListTile(
              key: const Key('event-all-day'),
              contentPadding: EdgeInsets.zero,
              title: const Text('All day'),
              value: _allDay,
              onChanged: clashes == null ? (v) => setState(() => _allDay = v) : null,
            ),
            if (!_allDay)
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      key: const Key('event-from'),
                      style: OutlinedButton.styleFrom(minimumSize: const Size(48, 48)),
                      onPressed: clashes == null ? () => _pickTime(true) : null,
                      child: Text('From ${_hm(_from)}'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton(
                      key: const Key('event-to'),
                      style: OutlinedButton.styleFrom(minimumSize: const Size(48, 48)),
                      onPressed: clashes == null ? () => _pickTime(false) : null,
                      child: Text('To ${_hm(_to)}'),
                    ),
                  ),
                ],
              ),
            const SizedBox(height: 8),
            TextField(
              key: const Key('event-location'),
              controller: _location,
              enabled: clashes == null,
              maxLength: 200,
              decoration: const InputDecoration(labelText: 'Place (optional)'),
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(_error!, style: const TextStyle(color: AccnomosColors.negText)),
              ),
            if (clashes != null) ...[
              Container(
                key: const Key('event-clash'),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFFFFF4E5),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: const Color(0xFFF2C38B)),
                ),
                child: Text([for (final c in clashes) c.sentence].join('\n'),
                    style: const TextStyle(color: Color(0xFF8A3F06), fontWeight: FontWeight.w600, height: 1.4)),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      key: const Key('event-cancel'),
                      style: OutlinedButton.styleFrom(minimumSize: const Size(48, 48)),
                      onPressed: _busy ? null : () => setState(() => _clashes = null),
                      child: const Text('Cancel'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: FilledButton(
                      key: const Key('event-add-anyway'),
                      style: FilledButton.styleFrom(
                          minimumSize: const Size(48, 48), backgroundColor: AccnomosColors.teal),
                      onPressed: _busy ? null : () => _submit(anyway: true),
                      child: const Text('Add anyway'),
                    ),
                  ),
                ],
              ),
            ] else
              FilledButton(
                key: const Key('event-submit'),
                style: FilledButton.styleFrom(minimumSize: const Size(48, 52), backgroundColor: AccnomosColors.teal),
                onPressed: _busy ? null : _submit,
                child: Text(_busy ? 'Checking your calendar…' : 'Add to calendar'),
              ),
          ],
        ),
      ),
    );
  }
}
