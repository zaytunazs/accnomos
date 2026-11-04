import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/calendar.dart';
import '../services/auth.dart';
import '../services/books.dart' show booksClient, ukDate;
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';

/// A runtime client, built when needed (a token may be asked for then).
typedef ClientFor = Future<RuntimeClient> Function();

/// A books client whose token can write the calendar (`Calendars.ReadWrite`,
/// asked for on first use, never at sign-in). In a demo it is the session id.
Future<RuntimeClient> calendarClient(
        AppSettings settings, AuthService auth, Account? account) async =>
    booksClient(settings, auth, account,
        graphToken: await auth.tokenFor(AuthService.calendarScopes));

/// The small print every calendar control carries: the product name only here.
const calendarSmallPrint =
    'Uses your Microsoft 365 / Outlook calendar, so the dates show on every device. '
    'Each deadline is an all-day event with a reminder at 9:00 the day before; '
    'Accnomos only changes events it added.';

/// The books' deadlines and whether they are in the calendar, shared by the
/// switch, the "Add to calendar" buttons and Home. [read] needs only the
/// sign-in; [write] carries the calendar scope (asked for on the first tap).
class DeadlineSync extends ChangeNotifier {
  DeadlineSync({required this.read, required this.write});

  final ClientFor read;
  final ClientFor write;

  CalendarDeadlines? deadlines;
  DeadlineSyncStatus? status;
  bool busy = false;
  bool loaded = false;
  String? message;

  /// Goes up after each sync that reached the calendar (the Calendar screen reloads).
  int syncs = 0;
  bool _disposed = false;

  CalendarDeadline? of(String kind) => deadlines?.of(kind);

  void _tell() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }

  static String _friendly(Object e) => e.toString().replaceFirst('Exception: ', '');

  /// `GET /calendar/deadlines` (it carries the status too).
  Future<void> load() async {
    try {
      final d = await (await read()).calendarDeadlines();
      deadlines = d;
      status = d.status;
    } catch (e) {
      message ??= _friendly(e);
    } finally {
      loaded = true;
      _tell();
    }
  }

  /// Everything ([keys] null) or only [keys].
  Future<void> sync({List<String>? keys}) async {
    if (busy) return;
    busy = true;
    message = null;
    _tell();
    try {
      final client = await write();
      final r = await client.syncDeadlines(keys: keys);
      final clash = r.conflicts.isEmpty ? '' : ' ${r.conflicts.first.b.sentence}.';
      message = r.message(one: keys != null) + clash;
      syncs++;
      final d = await client.calendarDeadlines();
      deadlines = d;
      status = d.status;
    } catch (e) {
      message = _friendly(e);
    } finally {
      busy = false;
      _tell();
    }
  }

  Future<void> syncOne(CalendarDeadline d) => sync(keys: [d.key]);

  /// The switch moves at once and goes back if the save fails; turning it on
  /// adds everything now.
  Future<void> setKeep(bool keep) async {
    final before = status;
    status = (status ?? const DeadlineSyncStatus(keep: false)).withKeep(keep);
    busy = true;
    message = null;
    _tell();
    try {
      status = await (await read()).setDeadlinesKeep(keep);
    } catch (e) {
      status = before;
      message = _friendly(e);
      busy = false;
      _tell();
      return;
    }
    busy = false;
    _tell();
    if (keep) await sync();
  }

  /// Home: with the switch on and the last update older than six hours.
  Future<void> autoSyncIfDue({DateTime? now}) async {
    final s = status;
    if (s != null && s.keep && s.stale(now: now)) await sync();
  }
}

/// "Add all deadlines to my calendar automatically", an "Add all to
/// calendar" button and "N deadlines in your calendar · updated HH:MM".
class CalendarSyncPanel extends StatelessWidget {
  const CalendarSyncPanel({super.key, required this.sync});

  final DeadlineSync sync;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: sync,
      builder: (context, _) {
        final status = sync.status;
        // A Material, not a coloured box: the switch's ink shows on it.
        return Material(
          key: const Key('calendar-sync-panel'),
          color: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
            side: const BorderSide(color: AccnomosColors.border),
          ),
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SwitchListTile(
                key: const Key('calendar-keep-switch'),
                contentPadding: EdgeInsets.zero,
                value: status?.keep ?? false,
                onChanged: sync.busy || status == null ? null : sync.setKeep,
                title: const Text('Add all deadlines to my calendar automatically',
                    style: TextStyle(fontWeight: FontWeight.w700, color: AccnomosColors.ink)),
              ),
              Text(
                sync.message ?? (status == null ? (sync.loaded ? '' : 'Loading…') : status.line()),
                key: const Key('calendar-sync-status'),
                style: const TextStyle(color: AccnomosColors.muted, height: 1.4),
              ),
              const SizedBox(height: 8),
              OutlinedButton(
                key: const Key('calendar-sync-all'),
                style: OutlinedButton.styleFrom(minimumSize: const Size(48, 48)),
                onPressed: sync.busy ? null : () => sync.sync(),
                child: Text(sync.busy ? 'Adding…' : 'Add all deadlines to calendar'),
              ),
              const SizedBox(height: 8),
              const Text(calendarSmallPrint,
                  style: TextStyle(color: AccnomosColors.muted, fontSize: 11, height: 1.4)),
            ],
            ),
          ),
        );
      },
    );
  }
}

/// "Add to calendar" for one deadline; "In your calendar ✓" once it is there.
class DeadlineCalendarButton extends StatelessWidget {
  const DeadlineCalendarButton({super.key, required this.sync, required this.deadline});

  final DeadlineSync sync;
  final CalendarDeadline deadline;

  @override
  Widget build(BuildContext context) {
    if (deadline.inCalendar) {
      return Semantics(
        label: 'In your calendar: ${deadline.title}',
        excludeSemantics: true,
        child: const Padding(
          padding: EdgeInsets.symmetric(vertical: 12),
          child: Text('In your calendar ✓',
              style: TextStyle(color: AccnomosColors.tealDark, fontWeight: FontWeight.w700)),
        ),
      );
    }
    return Semantics(
      button: true,
      label: 'Add to calendar: ${deadline.title}',
      excludeSemantics: true,
      child: TextButton(
        key: Key('add-deadline-${deadline.key}'),
        style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
        onPressed: sync.busy ? null : () => sync.syncOne(deadline),
        child: const Text('Add to calendar'),
      ),
    );
  }
}

/// Home › Deadlines: each upcoming deadline with its own "Add to calendar".
/// Turns the automatic switch's refresh on when it is due.
class HomeDeadlinesCard extends StatefulWidget {
  const HomeDeadlinesCard({super.key, required this.sync, this.onOpenCalendar, this.now});

  final DeadlineSync sync;
  final VoidCallback? onOpenCalendar;

  /// Tests: the clock the six-hour refresh compares with.
  final DateTime? now;

  @override
  State<HomeDeadlinesCard> createState() => _HomeDeadlinesCardState();
}

class _HomeDeadlinesCardState extends State<HomeDeadlinesCard> {
  @override
  void initState() {
    super.initState();
    widget.sync.load().then((_) => widget.sync.autoSyncIfDue(now: widget.now));
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.sync,
      builder: (context, _) {
        final items = widget.sync.deadlines?.items ?? const <CalendarDeadline>[];
        if (widget.sync.loaded && items.isEmpty) return const SizedBox.shrink();
        return Container(
          key: const Key('home-deadlines-card'),
          padding: const EdgeInsets.fromLTRB(14, 12, 6, 8),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: AccnomosColors.border),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Deadlines',
                  style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16, color: AccnomosColors.ink)),
              if (!widget.sync.loaded)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: LinearProgressIndicator(minHeight: 2, color: AccnomosColors.teal),
                ),
              for (final d in items.take(5))
                Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(d.title,
                              style: const TextStyle(fontWeight: FontWeight.w700, color: AccnomosColors.ink)),
                          Text(ukDate(d.day), style: const TextStyle(color: AccnomosColors.muted, fontSize: 12)),
                        ],
                      ),
                    ),
                    DeadlineCalendarButton(sync: widget.sync, deadline: d),
                  ],
                ),
              if (widget.sync.message != null)
                Padding(
                  padding: const EdgeInsets.only(top: 4, right: 8),
                  child: Text(widget.sync.message!,
                      style: const TextStyle(color: AccnomosColors.muted, fontSize: 12, height: 1.4)),
                ),
              if (widget.onOpenCalendar != null)
                TextButton(
                  key: const Key('home-open-calendar'),
                  style: TextButton.styleFrom(minimumSize: const Size(48, 48), padding: EdgeInsets.zero),
                  onPressed: widget.onOpenCalendar,
                  child: const Text('Open your calendar'),
                ),
            ],
          ),
        );
      },
    );
  }
}

/// The VAT due line on the VAT tab: "VAT return … due 7 Dec 2026" with its
/// own "Add to calendar".
class VatDueCalendarLine extends StatefulWidget {
  const VatDueCalendarLine({super.key, required this.sync});

  final DeadlineSync sync;

  @override
  State<VatDueCalendarLine> createState() => _VatDueCalendarLineState();
}

class _VatDueCalendarLineState extends State<VatDueCalendarLine> {
  @override
  void initState() {
    super.initState();
    widget.sync.load();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.sync,
      builder: (context, _) {
        final vat = widget.sync.of('vat');
        if (vat == null) return const SizedBox.shrink();
        return Row(
          key: const Key('vat-due-line'),
          children: [
            Expanded(
              child: Text('${vat.title} · ${ukDate(vat.day)}',
                  style: const TextStyle(fontWeight: FontWeight.w700, color: AccnomosColors.ink)),
            ),
            DeadlineCalendarButton(sync: widget.sync, deadline: vat),
          ],
        );
      },
    );
  }
}
