import 'package:flutter/material.dart';

import '../models/storage.dart';
import '../services/books.dart' show friendly;
import '../services/runtime_client.dart';
import '../theme.dart';
import 'home_cards.dart' show HomeCard;

/// Files › storage, like the web's Storage panel but read-only: totals, the
/// biggest folders and the tax years, how many duplicate sets there are, and
/// a "Back up now" button (`POST /backups`). Archiving, moving and Clean up
/// stay on the web, where there is room to preview them.
class StorageCard extends StatefulWidget {
  const StorageCard({super.key, required this.clientFor});

  /// A client with the signed-in books credentials (fresh token each call).
  final Future<RuntimeClient> Function() clientFor;

  @override
  State<StorageCard> createState() => _StorageCardState();
}

class _StorageCardState extends State<StorageCard> {
  StorageOverview? _overview;
  String? _error;
  String? _note;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _fetch();
  }

  Future<void> _fetch() async {
    try {
      final overview = await (await widget.clientFor()).storageOverview();
      if (!mounted) return;
      setState(() {
        _overview = overview;
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = friendly(e));
    }
  }

  Future<void> _backUp() async {
    setState(() {
      _busy = true;
      _note = null;
    });
    try {
      final r = await (await widget.clientFor()).backUpNow();
      final backup = r['backup'] is Map
          ? Map<String, dynamic>.from(r['backup'] as Map)
          : const <String, dynamic>{};
      final retired = r['retired'] is List ? (r['retired'] as List).length : 0;
      final files = backup['files'] is num
          ? (backup['files'] as num).toInt()
          : 0;
      if (!mounted) return;
      setState(
        () => _note =
            'Backed up $files ${files == 1 ? 'file' : 'files'} to ${backup['path'] ?? 'Backups'}'
            '${retired > 0 ? '. $retired older ${retired == 1 ? 'backup' : 'backups'} moved to _Trash.' : '.'}',
      );
      await _fetch();
    } catch (e) {
      if (mounted) setState(() => _note = 'Could not back up: ${friendly(e)}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  static const _row = TextStyle(
    color: AccnomosColors.ink,
    fontSize: 13,
    height: 1.4,
  );
  static const _muted = TextStyle(
    color: AccnomosColors.muted,
    fontSize: 13,
    height: 1.4,
  );

  Widget _use(StorageUse u, String unit) => Padding(
    padding: const EdgeInsets.only(top: 4),
    child: Row(
      children: [
        Expanded(
          child: Text(
            u.name.isEmpty ? 'Top level' : u.name,
            style: _row,
            overflow: TextOverflow.ellipsis,
            softWrap: false,
          ),
        ),
        const SizedBox(width: 8),
        Text(
          '${u.files} ${u.files == 1 ? unit : '${unit}s'} · ${sizeLabel(u.bytes)}',
          style: _muted,
        ),
      ],
    ),
  );

  @override
  Widget build(BuildContext context) {
    final o = _overview;
    return HomeCard(
      label: 'Storage',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (o == null && _error == null)
            const Padding(
              padding: EdgeInsets.only(top: 8),
              child: Text('Adding up your storage…', style: _muted),
            ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                _error!,
                key: const Key('storage-error'),
                style: _muted,
              ),
            ),
          if (o != null) ...[
            const SizedBox(height: 6),
            Text(
              '${o.totalFiles} files · ${sizeLabel(o.totalBytes)}${o.truncated ? ' (partial)' : ''}',
              key: const Key('storage-total'),
              style: const TextStyle(
                color: AccnomosColors.ink,
                fontSize: 16,
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              'By folder',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800),
            ),
            for (final f in o.folders.take(5)) _use(f, 'file'),
            if (o.years.isNotEmpty) ...[
              const SizedBox(height: 8),
              const Text(
                'By tax year',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800),
              ),
              for (final y in o.years.take(4)) _use(y, 'document'),
            ],
            const SizedBox(height: 8),
            Text(
              o.duplicateSets == 0
                  ? 'No duplicate files.'
                  : '${o.duplicateSets} ${o.duplicateSets == 1 ? 'set' : 'sets'} of duplicates '
                        '(${sizeLabel(o.duplicateBytes)}). Clean up on the web moves copies to _Trash.',
              key: const Key('storage-duplicates'),
              style: _muted,
            ),
          ],
          if (_note != null) ...[
            const SizedBox(height: 8),
            Semantics(
              liveRegion: true,
              child: Text(
                _note!,
                key: const Key('backup-note'),
                style: const TextStyle(
                  color: AccnomosColors.tealDark,
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  height: 1.4,
                ),
              ),
            ),
          ],
          const SizedBox(height: 10),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: AccnomosColors.teal,
                minimumSize: const Size.fromHeight(46),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
              ),
              onPressed: _busy ? null : _backUp,
              child: Text(
                _busy ? 'Backing up…' : 'Back up now',
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
