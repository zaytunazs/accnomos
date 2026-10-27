import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

/// A receipt photo (or PDF) waiting to reach the `00 Inbox` folder.
///
/// Pure Dart: no widgets, no platform channels, so the queue states and the
/// crop maths stay unit-testable.
enum CaptureStatus {
  /// Waiting for upload (or waiting for the network to return).
  queued,

  /// An upload is in flight.
  uploading,

  /// Safely in `00 Inbox` under [CaptureItem.inboxName].
  uploaded,

  /// The last attempt failed; [CaptureItem.error] says why. Retryable.
  failed,
}

/// A normalised crop rectangle in original-image coordinates.
///
/// Each edge is 0..1. `full` means "no crop". [quarterTurn] rotates the
/// rectangle 90 degrees clockwise inside the unit square, so a selection
/// drawn on screen keeps covering the same content when the image turns.
class CropRect {
  const CropRect({
    required this.left,
    required this.top,
    required this.right,
    required this.bottom,
  });

  final double left;
  final double top;
  final double right;
  final double bottom;

  factory CropRect.full() => const CropRect(
        left: 0,
        top: 0,
        right: 1,
        bottom: 1,
      );

  /// Clamp every edge to 0..1 and put them back in order.
  CropRect normalised() {
    final l = left.clamp(0.0, 1.0);
    final t = top.clamp(0.0, 1.0);
    final r = right.clamp(0.0, 1.0);
    final b = bottom.clamp(0.0, 1.0);
    return CropRect(
      left: l < r ? l : r,
      top: t < b ? t : b,
      right: l < r ? r : l,
      bottom: t < b ? b : t,
    );
  }

  /// True when the rectangle covers the whole image (no crop).
  bool get isFull {
    const eps = 1e-6;
    return left <= eps && top <= eps && right >= 1 - eps && bottom >= 1 - eps;
  }

  /// Rotate 90 degrees clockwise inside the unit square.
  ///
  /// A point (x, y) turns into (1 − y, x), so the corners (l, t) and (r, b)
  /// become (1 − b, l) and (1 − t, r). Four turns return the start.
  CropRect quarterTurn() => CropRect(
        left: 1 - bottom,
        top: left,
        right: 1 - top,
        bottom: right,
      ).normalised();

  /// Pixel box inside a [width]×[height] image, at least 1 px each way.
  CropPixels toPixels(int width, int height) {
    final n = normalised();
    var x0 = (n.left * width).floor();
    var y0 = (n.top * height).floor();
    var x1 = (n.right * width).ceil();
    var y1 = (n.bottom * height).ceil();
    x0 = x0.clamp(0, width - 1);
    y0 = y0.clamp(0, height - 1);
    x1 = x1.clamp(x0 + 1, width);
    y1 = y1.clamp(y0 + 1, height);
    return CropPixels(x: x0, y: y0, width: x1 - x0, height: y1 - y0);
  }

  Map<String, dynamic> toJson() => {
        'l': left,
        't': top,
        'r': right,
        'b': bottom,
      };

  factory CropRect.fromJson(Map<String, dynamic> json) => CropRect(
        left: (json['l'] as num?)?.toDouble() ?? 0,
        top: (json['t'] as num?)?.toDouble() ?? 0,
        right: (json['r'] as num?)?.toDouble() ?? 1,
        bottom: (json['b'] as num?)?.toDouble() ?? 1,
      ).normalised();

  @override
  bool operator ==(Object other) =>
      other is CropRect &&
      (left - other.left).abs() < 1e-9 &&
      (top - other.top).abs() < 1e-9 &&
      (right - other.right).abs() < 1e-9 &&
      (bottom - other.bottom).abs() < 1e-9;

  @override
  int get hashCode => Object.hash(left, top, right, bottom);
}

/// Integer pixel box for [CropRect.toPixels].
class CropPixels {
  const CropPixels({
    required this.x,
    required this.y,
    required this.width,
    required this.height,
  });

  final int x;
  final int y;
  final int width;
  final int height;
}

/// One photo or PDF staged for upload to `00 Inbox`.
class CaptureItem {
  CaptureItem({
    String? id,
    required this.path,
    required this.ext,
    this.status = CaptureStatus.queued,
    this.error,
    this.inboxName,
    this.rotationQuarters = 0,
    this.crop,
  }) : id = id ?? 'cap-${DateTime.now().microsecondsSinceEpoch}';

  final String id;

  /// Staged file on this phone (app cache copy, never the gallery original).
  final String path;

  /// Lower-case extension with the dot, e.g. `.jpg` or `.pdf`.
  final String ext;

  final CaptureStatus status;
  final String? error;

  /// `receipt-<stamp>-<n>.<ext>` once uploaded.
  final String? inboxName;

  /// Clockwise quarter turns chosen in the preview (0–3).
  final int rotationQuarters;

  /// Corner crop in original-image coordinates; null means the full frame.
  final CropRect? crop;

  bool get isPdf => ext == '.pdf';

  bool get edited =>
      rotationQuarters % 4 != 0 || (crop != null && !crop!.isFull);

  String get displayName {
    final base = path.split(RegExp(r'[/\\]')).last;
    return base.isEmpty ? 'receipt$ext' : base;
  }

  CaptureItem copyWith({
    CaptureStatus? status,
    String? error,
    bool clearError = false,
    String? inboxName,
    int? rotationQuarters,
    CropRect? crop,
    bool clearCrop = false,
  }) {
    return CaptureItem(
      id: id,
      path: path,
      ext: ext,
      status: status ?? this.status,
      error: clearError ? null : (error ?? this.error),
      inboxName: inboxName ?? this.inboxName,
      rotationQuarters: rotationQuarters ?? this.rotationQuarters,
      crop: clearCrop ? null : (crop ?? this.crop),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'path': path,
        'ext': ext,
        'status': status.name,
        'error': error,
        'inboxName': inboxName,
        'rotationQuarters': rotationQuarters,
        'crop': crop?.toJson(),
      };

  factory CaptureItem.fromJson(Map<String, dynamic> json) {
    final statusName = (json['status'] ?? 'queued').toString();
    final status = CaptureStatus.values.asNameMap()[statusName] ??
        CaptureStatus.queued;
    // An upload cannot still be in flight after a restart: park it back in
    // the queue so it retries instead of sticking on a spinner.
    final parked =
        status == CaptureStatus.uploading ? CaptureStatus.queued : status;
    final cropJson = json['crop'];
    return CaptureItem(
      id: (json['id'] ?? '').toString(),
      path: (json['path'] ?? '').toString(),
      ext: ((json['ext'] ?? '.jpg') as String).toLowerCase(),
      status: parked,
      error: (json['error'] as String?)?.isEmpty ?? true
          ? null
          : json['error'] as String?,
      inboxName: json['inboxName'] as String?,
      rotationQuarters:
          ((json['rotationQuarters'] as num?)?.toInt() ?? 0) % 4,
      crop: cropJson is Map
          ? CropRect.fromJson(Map<String, dynamic>.from(cropJson))
          : null,
    );
  }
}

/// `receipt-20261027120000-2.jpg`: stamp plus the 1-based place in the batch.
String inboxNameFor(String stamp, int index, String ext) =>
    'receipt-$stamp-${index + 1}$ext';

/// `20261027120000` from a [DateTime], 14 digits.
String stampFor(DateTime when) {
  String two(int v) => v.toString().padLeft(2, '0');
  return '${when.year}${two(when.month)}${two(when.day)}'
      '${two(when.hour)}${two(when.minute)}${two(when.second)}';
}

/// Lower-case extension with the dot, defaulting to `.jpg`.
String extFor(String path) {
  final base = path.split(RegExp(r'[/\\]')).last;
  final dot = base.lastIndexOf('.');
  if (dot < 0) return '.jpg';
  final ext = base.substring(dot).toLowerCase();
  if (ext == '.jpeg') return '.jpg';
  return ext;
}

/// Graph content type for an inbox upload.
String contentTypeFor(String path) {
  final lower = path.toLowerCase();
  if (lower.endsWith('.png')) return 'image/png';
  if (lower.endsWith('.pdf')) return 'application/pdf';
  if (lower.endsWith('.heic') || lower.endsWith('.heif')) {
    return 'image/heic';
  }
  return 'image/jpeg';
}

/// What the Capture screen hands back to Review after a signed-in scan.
class CaptureScanSummary {
  const CaptureScanSummary({required this.fresh, required this.needALook});

  /// Proposals fresh from this scan.
  final int fresh;

  /// Files the reader could not read.
  final int needALook;

  /// `3 new, 1 needs a look` in UK English.
  String get label {
    final freshBit =
        '$fresh new proposal${fresh == 1 ? '' : 's'}';
    if (needALook == 0) return freshBit;
    return '$freshBit, $needALook need${needALook == 1 ? 's' : ''} a look';
  }
}

/// The persisted capture queue: item metadata as JSON in app storage.
///
/// The photo bytes live as staged files next to it; when a staged file is
/// gone (cache cleared), the item is kept with a clear error rather than
/// dropped silently.
class CaptureQueueStore {
  static const key = 'accnomos.captureQueue.v1';

  static Future<List<CaptureItem>> load() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(key);
    if (raw == null || raw.isEmpty) return const [];
    try {
      final decoded = json.decode(raw);
      if (decoded is! List) return const [];
      return [
        for (final entry in decoded)
          if (entry is Map)
            CaptureItem.fromJson(Map<String, dynamic>.from(entry)),
      ];
    } catch (_) {
      return const [];
    }
  }

  static Future<void> save(List<CaptureItem> items) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      key,
      json.encode([for (final item in items) item.toJson()]),
    );
  }

  static Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(key);
  }
}
