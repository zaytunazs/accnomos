import 'package:shared_preferences/shared_preferences.dart';

/// Settings › Business setup kept on this phone, as the web keeps them in
/// the browser (apps/web/src/lib/business.ts, lib/triage.ts): the day
/// planner's working hours and visit limit, and whether Home checks the
/// inbox by itself. Nothing here goes to the books.
class BusinessPrefs {
  const BusinessPrefs({
    this.workStart = defaultStart,
    this.workEnd = defaultEnd,
    this.maxVisits = defaultVisits,
    this.triageOnHome = false,
  });

  static const defaultStart = '08:00';
  static const defaultEnd = '17:30';
  static const defaultVisits = 5;

  final String workStart; // HH:MM
  final String workEnd; // HH:MM
  final int maxVisits; // 1..12
  final bool triageOnHome;

  static final _hhmm = RegExp(r'^([01]\d|2[0-3]):[0-5]\d$');

  static bool validTime(String v) => _hhmm.hasMatch(v);

  /// Null when the hours are fine, else why not.
  static String? problem(String start, String end) {
    if (!validTime(start) || !validTime(end)) return 'Times are HH:MM, e.g. 08:00.';
    if (start.compareTo(end) >= 0) return 'The working day must end after it starts.';
    return null;
  }

  /// The planner body (`POST /plan/day` constraints).
  Map<String, dynamic> get constraints =>
      {'start': workStart, 'end': workEnd, 'max_visits': maxVisits};

  BusinessPrefs copyWith({String? workStart, String? workEnd, int? maxVisits, bool? triageOnHome}) =>
      BusinessPrefs(
        workStart: workStart ?? this.workStart,
        workEnd: workEnd ?? this.workEnd,
        maxVisits: maxVisits ?? this.maxVisits,
        triageOnHome: triageOnHome ?? this.triageOnHome,
      );

  static Future<BusinessPrefs> load() async {
    final p = await SharedPreferences.getInstance();
    final start = p.getString('business.work_start') ?? defaultStart;
    final end = p.getString('business.work_end') ?? defaultEnd;
    final ok = problem(start, end) == null;
    final visits = p.getInt('business.max_visits') ?? defaultVisits;
    return BusinessPrefs(
      workStart: ok ? start : defaultStart,
      workEnd: ok ? end : defaultEnd,
      maxVisits: visits >= 1 && visits <= 12 ? visits : defaultVisits,
      triageOnHome: p.getBool('business.triage_on_home') ?? false,
    );
  }

  Future<void> save() async {
    final p = await SharedPreferences.getInstance();
    await p.setString('business.work_start', workStart);
    await p.setString('business.work_end', workEnd);
    await p.setInt('business.max_visits', maxVisits);
    await p.setBool('business.triage_on_home', triageOnHome);
  }
}
