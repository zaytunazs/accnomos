/// A proposed day from `POST /plan/day` (see `RtPlan` in
/// `apps/web/src/lib/runtime.ts`). Times carry their UK offset. Nothing is
/// written until `POST /plan/day/apply`.
class DayPlan {
  DayPlan({
    required this.date,
    required this.items,
    required this.rationaleMd,
    this.warnings = const [],
    this.planHash = '',
    this.model,
    this.fallbackReason,
  });

  final String date;
  final List<DayPlanItem> items;
  final String rationaleMd;
  final List<String> warnings;
  final String planHash;
  final String? model;
  final String? fallbackReason;

  factory DayPlan.fromJson(Map<String, dynamic> json) {
    return DayPlan(
      date: (json['date'] ?? '').toString(),
      items: [
        if (json['plan'] is List)
          for (final i in json['plan'] as List)
            if (i is Map) DayPlanItem.fromJson(Map<String, dynamic>.from(i)),
      ],
      rationaleMd: (json['rationale_md'] ?? '').toString(),
      warnings: [
        if (json['warnings'] is List)
          for (final w in json['warnings'] as List) w.toString(),
      ],
      planHash: (json['plan_hash'] ?? '').toString(),
      model: json['model']?.toString(),
      fallbackReason: json['fallback_reason']?.toString(),
    );
  }

  /// Items that Apply would create (everything except `existing`).
  List<DayPlanItem> get fresh =>
      [for (final i in items) if (i.kind != 'existing') i];
}

/// One line of the proposed day.
class DayPlanItem {
  DayPlanItem({
    required this.kind,
    required this.start,
    required this.end,
    required this.title,
    this.jobId,
    this.location,
  });

  /// `visit`, `travel`, `lunch`, `admin` or `existing`.
  final String kind;
  final String start;
  final String end;
  final String title;
  final String? jobId;
  final String? location;

  factory DayPlanItem.fromJson(Map<String, dynamic> json) {
    return DayPlanItem(
      kind: (json['kind'] ?? '').toString(),
      start: (json['start'] ?? '').toString(),
      end: (json['end'] ?? '').toString(),
      title: (json['title'] ?? '').toString(),
      jobId: json['job_id']?.toString(),
      location: json['location']?.toString(),
    );
  }

  Map<String, dynamic> toJson() => {
        'kind': kind,
        'start': start,
        'end': end,
        'job_id': jobId,
        'title': title,
        'location': location,
      };
}

/// What `POST /plan/day/apply` created in Outlook.
class AppliedPlan {
  AppliedPlan({
    required this.date,
    required this.created,
    required this.alreadyApplied,
    required this.mileageNotes,
  });

  final String date;
  final List<String> created;
  final bool alreadyApplied;
  final int mileageNotes;

  factory AppliedPlan.fromJson(Map<String, dynamic> json) {
    final created = <String>[];
    if (json['created'] is List) {
      for (final c in json['created'] as List) {
        if (c is Map && c['reused'] != true) {
          created.add((c['title'] ?? '').toString());
        }
      }
    }
    var mileage = 0;
    if (json['mileage_proposals'] is List) {
      mileage = (json['mileage_proposals'] as List).length;
    }
    return AppliedPlan(
      date: (json['date'] ?? '').toString(),
      created: created,
      alreadyApplied: json['already_applied'] == true,
      mileageNotes: mileage,
    );
  }
}
