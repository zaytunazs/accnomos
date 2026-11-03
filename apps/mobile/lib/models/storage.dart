/// `GET /files/overview` (services/runtime/app/files.py): counts and sizes
/// per folder and per tax year, and the duplicate copies Clean up moves to
/// _Trash (`POST /files/trash`): every copy except the one kept, never a
/// document the books link to.
class StorageUse {
  const StorageUse(this.name, this.files, this.bytes);
  final String name;
  final int files;
  final int bytes;
}

class StorageOverview {
  const StorageOverview({
    required this.totalFiles,
    required this.totalBytes,
    this.folders = const [],
    this.years = const [],
    this.duplicateSets = 0,
    this.duplicateBytes = 0,
    this.truncated = false,
    this.cleanUpPaths = const [],
  });

  final int totalFiles;
  final int totalBytes;
  final List<StorageUse> folders; // biggest first
  final List<StorageUse> years; // tax years, newest first
  final int duplicateSets;
  final int duplicateBytes;
  final bool truncated;

  /// The copies Clean up would move to _Trash (not the kept one, not linked).
  final List<String> cleanUpPaths;

  factory StorageOverview.fromJson(Map<String, dynamic> j) {
    int n(Object? v) => v is num ? v.toInt() : 0;
    List<StorageUse> uses(Object? list, String key) => [
      if (list is List)
        for (final x in list)
          if (x is Map)
            StorageUse('${x[key] ?? ''}', n(x['files']), n(x['bytes'])),
    ];
    final dupes = j['duplicates'];
    final paths = <String>[
      if (dupes is List)
        for (final g in dupes)
          if (g is Map && g['files'] is List)
            for (final f in g['files'] as List)
              if (f is Map && f['keep'] != true && f['linked'] != true && f['protected'] != true)
                '${f['path']}',
    ];
    return StorageOverview(
      totalFiles: n(j['total_files']),
      totalBytes: n(j['total_bytes']),
      folders: uses(j['folders'], 'folder'),
      years: uses(j['years'], 'year'),
      duplicateSets: dupes is List ? dupes.length : 0,
      duplicateBytes: n(j['duplicate_bytes']),
      truncated: j['truncated'] == true,
      cleanUpPaths: paths,
    );
  }
}

/// 1536 → "2 KB", like the web's `bytes()` in components/files/manage.tsx.
String sizeLabel(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).round()} KB';
  if (bytes < 1024 * 1024 * 1024) {
    final mb = bytes / 1024 / 1024;
    return '${mb.toStringAsFixed(mb < 10 ? 1 : 0)} MB';
  }
  return '${(bytes / 1024 / 1024 / 1024).toStringAsFixed(2)} GB';
}
