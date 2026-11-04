/// The user's calendar, as the runtime's `/calendar/*` routes give it
/// (services/runtime/app/routes_calendar.py). Times arrive as Europe/London
/// ISO strings; the phone shows the wall-clock part as sent (no device-zone
/// conversion), so 09:00 in London reads 09:00 wherever the phone is.
library;

String _s(Object? v) => (v ?? '').toString();

/// `YYYY-MM-DD` of an ISO date or date-time string.
String isoDay(String iso) => iso.length >= 10 ? iso.substring(0, 10) : iso;

/// `HH:MM` of an ISO date-time string, or '' for a bare date.
String isoTime(String iso) => iso.length >= 16 && iso[10] == 'T' ? iso.substring(11, 16) : '';

/// One event in the calendar (`EventOut`).
class CalendarEvent {
  const CalendarEvent({
    required this.id,
    required this.subject,
    required this.start,
    required this.end,
    required this.allDay,
    this.location,
    this.accnomos = false,
    this.webLink,
  });

  final String id;
  final String subject;
  final String start;
  final String end;
  final bool allDay;
  final String? location;

  /// Written by Accnomos (shows the "Added by Accnomos" chip).
  final bool accnomos;
  final String? webLink;

  String get day => isoDay(start);

  /// "09:00–10:00", or "All day".
  String get when => allDay ? 'All day' : '${isoTime(start)}–${isoTime(end)}';

  factory CalendarEvent.fromJson(Map<String, dynamic> j) => CalendarEvent(
        id: _s(j['id']),
        subject: _s(j['subject']),
        start: _s(j['start']),
        end: _s(j['end']),
        allDay: j['all_day'] == true,
        location: j['location'] == null || _s(j['location']).isEmpty ? null : _s(j['location']),
        accnomos: j['accnomos'] == true,
        webLink: j['web_link'] == null ? null : _s(j['web_link']),
      );

  static List<CalendarEvent> listFromJson(Object? raw) => [
        if (raw is List)
          for (final x in raw)
            if (x is Map) CalendarEvent.fromJson(Map<String, dynamic>.from(x)),
      ];
}

/// An event a new one would clash with (`Clash`).
class CalendarClash {
  const CalendarClash({required this.subject, required this.start, required this.end, required this.allDay});

  final String subject;
  final String start;
  final String end;
  final bool allDay;

  /// "Clashes with 'Site meeting' 09:00–10:00" (or "(all day)").
  String get sentence =>
      "Clashes with '$subject' ${allDay ? '(all day)' : '${isoTime(start)}–${isoTime(end)}'}";

  factory CalendarClash.fromJson(Map<String, dynamic> j) => CalendarClash(
        subject: _s(j['subject']),
        start: _s(j['start']),
        end: _s(j['end']),
        allDay: j['all_day'] == true,
      );

  static List<CalendarClash> listFromJson(Object? raw) => [
        if (raw is List)
          for (final x in raw)
            if (x is Map) CalendarClash.fromJson(Map<String, dynamic>.from(x)),
      ];
}

/// Two events already in the calendar that clash (`ClashPair`).
class CalendarClashPair {
  const CalendarClashPair(this.a, this.b);
  final CalendarClash a;
  final CalendarClash b;

  static List<CalendarClashPair> listFromJson(Object? raw) => [
        if (raw is List)
          for (final x in raw)
            if (x is Map && x['a'] is Map && x['b'] is Map)
              CalendarClashPair(
                CalendarClash.fromJson(Map<String, dynamic>.from(x['a'] as Map)),
                CalendarClash.fromJson(Map<String, dynamic>.from(x['b'] as Map)),
              ),
      ];
}

/// One deadline "Add to calendar" would add (`GET /calendar/deadlines`).
class CalendarDeadline {
  const CalendarDeadline({
    required this.key,
    required this.kind,
    required this.title,
    required this.day,
    required this.inCalendar,
  });

  /// Stable key (`deadline:vat:…`, `invoice:INV-0042`), sent back to add only this one.
  final String key;

  /// vat | itsa | self_assessment | cis | payroll | invoice
  final String kind;
  final String title;
  final String day;
  final bool inCalendar;

  CalendarDeadline added() =>
      CalendarDeadline(key: key, kind: kind, title: title, day: day, inCalendar: true);

  factory CalendarDeadline.fromJson(Map<String, dynamic> j) => CalendarDeadline(
        key: _s(j['key']),
        kind: _s(j['kind']),
        title: _s(j['title']),
        day: isoDay(_s(j['day'])),
        inCalendar: j['in_calendar'] == true,
      );
}

/// `GET /calendar/deadlines`: the items plus the sync status.
class CalendarDeadlines {
  const CalendarDeadlines({required this.items, required this.status});
  final List<CalendarDeadline> items;
  final DeadlineSyncStatus status;

  /// The first upcoming deadline of [kind], or null.
  CalendarDeadline? of(String kind) {
    for (final i in items) {
      if (i.kind == kind) return i;
    }
    return null;
  }

  factory CalendarDeadlines.fromJson(Map<String, dynamic> j) => CalendarDeadlines(
        items: [
          if (j['items'] is List)
            for (final x in j['items'] as List)
              if (x is Map) CalendarDeadline.fromJson(Map<String, dynamic>.from(x)),
        ],
        status: DeadlineSyncStatus.fromJson(j),
      );
}

/// `GET /calendar/deadlines/status` (and the preference's answer).
class DeadlineSyncStatus {
  const DeadlineSyncStatus({required this.keep, this.lastSync, this.count = 0, bool? synced})
      : synced = synced ?? lastSync != null;

  final bool synced;

  /// "Add all deadlines to my calendar automatically".
  final bool keep;
  final String? lastSync;
  final int count;

  DeadlineSyncStatus withKeep(bool keep) =>
      DeadlineSyncStatus(keep: keep, lastSync: lastSync, count: count, synced: synced);

  /// "3 deadlines in your calendar · updated 09:15" (or "updated 3 Nov").
  String line({DateTime? now}) {
    if (!synced || lastSync == null) return 'No deadlines in your calendar yet.';
    return '$count deadline${count == 1 ? '' : 's'} in your calendar · ${updatedLabel(lastSync!, now: now)}';
  }

  /// Older than six hours: the automatic switch refreshes on Home.
  bool stale({DateTime? now}) {
    final at = lastSync == null ? null : DateTime.tryParse(lastSync!);
    return at == null || (now ?? DateTime.now()).difference(at) > const Duration(hours: 6);
  }

  factory DeadlineSyncStatus.fromJson(Map<String, dynamic> j) {
    final last = j['last_sync'];
    return DeadlineSyncStatus(
      keep: j['keep'] == true,
      lastSync: last == null || _s(last).isEmpty ? null : _s(last),
      count: (j['count'] as num?)?.toInt() ?? 0,
      synced: j['synced'] is bool ? j['synced'] as bool : null,
    );
  }
}

const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/// "updated 09:15" on the day (London wall-clock as sent), else "updated 3 Nov".
String updatedLabel(String iso, {DateTime? now}) {
  final day = DateTime.tryParse(isoDay(iso));
  final today = now ?? DateTime.now();
  if (day == null) return 'updated';
  final same = day.year == today.year && day.month == today.month && day.day == today.day;
  return same && isoTime(iso).isNotEmpty
      ? 'updated ${isoTime(iso)}'
      : 'updated ${day.day} ${_months[day.month - 1]}';
}

/// "Thu 29 Oct", for a `YYYY-MM-DD` day heading.
String dayHeading(String day) {
  final d = DateTime.tryParse(day);
  if (d == null) return day;
  const names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  return '${names[d.weekday - 1]} ${d.day} ${_months[d.month - 1]}';
}

/// `POST /calendar/deadlines/sync`.
class DeadlineSyncResult {
  const DeadlineSyncResult({
    required this.added,
    required this.updated,
    required this.unchanged,
    required this.removed,
    required this.events,
    required this.conflicts,
  });

  final int added;
  final int updated;
  final int unchanged;
  final int removed;
  final List<CalendarEvent> events;
  final List<CalendarClashPair> conflicts;

  /// What the panel says after a sync of everything ([one] false) or of one deadline.
  String message({bool one = false}) {
    if (one) {
      return added + updated == 0
          ? 'Already in your calendar.'
          : 'Added to your calendar: ${events.map((e) => e.subject).join(', ')}.';
    }
    final parts = [
      if (added > 0) '$added added',
      if (updated > 0) '$updated updated',
      if (removed > 0) '$removed removed',
    ];
    return parts.isEmpty ? 'Your calendar already has every deadline.' : 'Done: ${parts.join(', ')}.';
  }

  factory DeadlineSyncResult.fromJson(Map<String, dynamic> j) => DeadlineSyncResult(
        added: (j['added'] as num?)?.toInt() ?? 0,
        updated: (j['updated'] as num?)?.toInt() ?? 0,
        unchanged: (j['unchanged'] as num?)?.toInt() ?? 0,
        removed: (j['removed'] as num?)?.toInt() ?? 0,
        events: CalendarEvent.listFromJson(j['events']),
        conflicts: CalendarClashPair.listFromJson(j['conflicts']),
      );
}
