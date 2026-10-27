import 'package:flutter/material.dart';

import '../theme.dart';

/// AI view text for one duplicate group: same or not, confidence, reason.
/// Null when the model could not answer: the code evidence stands alone.
String? duplicateAiText(Map<String, dynamic>? ai, bool blocked) {
  if (ai == null) return null;
  final reason = (ai['reason'] ?? '').toString().trim();
  if (blocked) {
    return reason.isEmpty
        ? 'Code rules this out: the VAT numbers differ, so these are two businesses.'
        : reason;
  }
  final same = ai['same'] == true;
  final confidence = ai['confidence'];
  final pct = confidence is num ? '${(confidence * 100).round()}%' : null;
  final verdict = same ? 'same business' : 'not the same';
  final head = pct == null ? 'AI view: $verdict' : 'AI view: $verdict ($pct)';
  return reason.isEmpty ? head : '$head: $reason';
}

/// Possible duplicates: code finds the candidates (shared email, phone, VAT
/// number or close name) with the evidence listed, and the model gives its
/// view beside it. Nothing merges until the user says so. [onMerge] folds
/// the group into the kept contact, [onDismiss] remembers a pair is not the
/// same, [onUndo] takes a merge back by its id; [onChanged] reloads the list
/// after each one.
class DuplicatesCard extends StatefulWidget {
  const DuplicatesCard({
    super.key,
    required this.groups,
    required this.onMerge,
    required this.onDismiss,
    required this.onUndo,
    required this.onChanged,
  });

  final List<Map<String, dynamic>> groups;
  final Future<Map<String, dynamic>> Function({
    required String keepId,
    required List<String> mergeIds,
    String? name,
  }) onMerge;
  final Future<void> Function(List<String> ids) onDismiss;
  final Future<void> Function(String mergeId) onUndo;
  final VoidCallback onChanged;

  @override
  State<DuplicatesCard> createState() => _DuplicatesState();
}

String _groupKey(Map<String, dynamic> g) =>
    ((g['contact_ids'] as List?) ?? const []).join(',');

List<Map<String, dynamic>> _groupMembers(Map<String, dynamic> g) => [
      for (final c in ((g['contacts'] as List?) ?? const []))
        if (c is Map) Map<String, dynamic>.from(c),
    ];

String _groupNames(Map<String, dynamic> g) => _groupMembers(g)
    .map((c) => (c['name'] ?? 'Unnamed').toString())
    .join(' + ');

class _DuplicatesState extends State<DuplicatesCard> {
  String? _busy;
  String? _error;
  ({String mergeId, String message})? _undone;

  Future<void> _dismiss(Map<String, dynamic> g) async {
    final key = _groupKey(g);
    setState(() {
      _busy = key;
      _error = null;
    });
    try {
      final ids = [
        for (final id in ((g['contact_ids'] as List?) ?? const []))
          id.toString(),
      ];
      await widget.onDismiss(ids);
      widget.onChanged();
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  Future<void> _merge(
      Map<String, dynamic> g, String keepId, String name) async {
    final key = 'merge:${_groupKey(g)}';
    setState(() {
      _busy = key;
      _error = null;
    });
    try {
      final others = [
        for (final id in ((g['contact_ids'] as List?) ?? const []))
          id.toString(),
      ].where((id) => id != keepId).toList();
      final result = await widget.onMerge(
          keepId: keepId,
          mergeIds: others,
          name: name.trim().isEmpty ? null : name.trim());
      if (!mounted) return;
      final kept = result['contact'];
      final keptName = kept is Map
          ? (kept['name'] ?? 'the kept contact').toString()
          : 'the kept contact';
      setState(() => _undone = (
            mergeId: (result['merge_id'] ?? '').toString(),
            message: 'Merged into $keptName.',
          ));
      widget.onChanged();
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  Future<void> _undo() async {
    final undone = _undone;
    if (undone == null) return;
    setState(() {
      _busy = 'undo';
      _error = null;
    });
    try {
      await widget.onUndo(undone.mergeId);
      if (!mounted) return;
      setState(() => _undone = null);
      widget.onChanged();
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  void _openGroup(Map<String, dynamic> g) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => _GroupSheet(
        group: g,
        busy: _busy != null,
        onMerge: () {
          Navigator.of(sheetContext).pop();
          _openMerge(g);
        },
        onDismiss: () {
          Navigator.of(sheetContext).pop();
          _dismiss(g);
        },
      ),
    );
  }

  void _openMerge(Map<String, dynamic> g) {
    final members = _groupMembers(g);
    final ai = g['ai'] is Map ? Map<String, dynamic>.from(g['ai']) : null;
    final keepName = (ai?['keep_name'] ?? '').toString();
    final suggested = members
        .where((c) => (c['name'] ?? '').toString() == keepName)
        .followedBy(members);
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => _MergeSheet(
        groupName: _groupNames(g),
        members: members,
        suggestedKeepId: suggested.isEmpty
            ? ''
            : (suggested.first['id'] ?? '').toString(),
        suggestedName: suggested.isEmpty
            ? ''
            : (suggested.first['name'] ?? '').toString(),
        busy: _busy != null,
        onConfirm: (keepId, name) {
          Navigator.of(sheetContext).pop();
          _merge(g, keepId, name);
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (widget.groups.isEmpty && _undone == null) {
      return const SizedBox.shrink();
    }
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(16, 8, 16, 0),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (widget.groups.isNotEmpty) ...[
            Text(
              'Possible duplicates (${widget.groups.length})',
              style: const TextStyle(
                  fontWeight: FontWeight.w800, fontSize: 16),
            ),
            const SizedBox(height: 4),
            const Text(
              'Code found these by shared email, phone, VAT number or close name. '
              'The AI view is advice only — nothing merges until you say so.',
              style:
                  TextStyle(fontSize: 13, color: AccnomosColors.muted),
            ),
            const SizedBox(height: 8),
            for (final g in widget.groups)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: SizedBox(
                  width: double.infinity,
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      alignment: Alignment.centerLeft,
                      foregroundColor: AccnomosColors.ink,
                      minimumSize: const Size(48, 48),
                    ),
                    onPressed: () => _openGroup(g),
                    child: Text(
                      _groupNames(g),
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                  ),
                ),
              ),
          ],
          if (_undone != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      _undone!.message,
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                  ),
                  TextButton(
                    style: TextButton.styleFrom(
                      foregroundColor: AccnomosColors.tealDark,
                      minimumSize: const Size(48, 48),
                    ),
                    onPressed: _busy != null ? null : _undo,
                    child: Text(_busy == 'undo' ? 'Undoing…' : 'Undo'),
                  ),
                ],
              ),
            ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(_error!,
                  style: const TextStyle(
                      fontSize: 13,
                      color: Color(0xFF8A3F06),
                      fontWeight: FontWeight.w600)),
            ),
        ],
      ),
    );
  }
}

/// One group: the code evidence and the AI's view, with Merge / Not the same.
class _GroupSheet extends StatelessWidget {
  const _GroupSheet({
    required this.group,
    required this.busy,
    required this.onMerge,
    required this.onDismiss,
  });

  final Map<String, dynamic> group;
  final bool busy;
  final VoidCallback onMerge;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final members = _groupMembers(group);
    final evidence = [
      for (final e in ((group['evidence'] as List?) ?? const []))
        e.toString(),
    ];
    final blocked = group['blocked'] == true;
    final ai =
        group['ai'] is Map ? Map<String, dynamic>.from(group['ai']) : null;
    final aiText = duplicateAiText(ai, blocked);
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              _groupNames(group),
              style:
                  const TextStyle(fontWeight: FontWeight.w800, fontSize: 18),
            ),
            const SizedBox(height: 8),
            for (final m in members)
              Padding(
                padding: const EdgeInsets.only(bottom: 2),
                child: Text(
                  [
                    (m['name'] ?? '').toString(),
                    if ((m['vrn'] ?? '').toString().isNotEmpty)
                      'VAT ${(m['vrn'] ?? '').toString()}',
                    if ((m['email'] ?? '').toString().isNotEmpty)
                      (m['email'] ?? '').toString(),
                  ].join(' · '),
                  style: const TextStyle(color: AccnomosColors.muted),
                ),
              ),
            const SizedBox(height: 8),
            const Text('Code evidence',
                style: TextStyle(fontWeight: FontWeight.w700)),
            for (final e in evidence) Text('• $e'),
            const SizedBox(height: 8),
            Text(
              aiText ?? 'The model could not answer — decide from the evidence above.',
              style: TextStyle(
                fontWeight: FontWeight.w600,
                color: aiText == null
                    ? AccnomosColors.muted
                    : AccnomosColors.tealDark,
              ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                if (!blocked)
                  Expanded(
                    child: FilledButton(
                      style: FilledButton.styleFrom(
                        backgroundColor: AccnomosColors.teal,
                        minimumSize: const Size.fromHeight(52),
                      ),
                      onPressed: busy ? null : onMerge,
                      child: const Text('Merge'),
                    ),
                  ),
                if (!blocked) const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AccnomosColors.tealDark,
                      minimumSize: const Size.fromHeight(52),
                    ),
                    onPressed: busy ? null : onDismiss,
                    child: const Text('Not the same'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// Confirm sheet naming the kept contact: which contact to keep plus the
/// name for the merged contact.
class _MergeSheet extends StatefulWidget {
  const _MergeSheet({
    required this.groupName,
    required this.members,
    required this.suggestedKeepId,
    required this.suggestedName,
    required this.busy,
    required this.onConfirm,
  });

  final String groupName;
  final List<Map<String, dynamic>> members;
  final String suggestedKeepId;
  final String suggestedName;
  final bool busy;
  final void Function(String keepId, String name) onConfirm;

  @override
  State<_MergeSheet> createState() => _MergeSheetState();
}

class _MergeSheetState extends State<_MergeSheet> {
  late String _keepId;
  final _name = TextEditingController();
  String? _error;

  @override
  void initState() {
    super.initState();
    _keepId = widget.suggestedKeepId;
    _name.text = widget.suggestedName;
  }

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SingleChildScrollView(
        padding: EdgeInsets.only(
          left: 16,
          right: 16,
          top: 16,
          bottom: 16 + MediaQuery.of(context).viewInsets.bottom,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'Keep which contact?',
              style: TextStyle(fontWeight: FontWeight.w800, fontSize: 18),
            ),
            const SizedBox(height: 4),
            Text(
              widget.groupName,
              style: const TextStyle(color: AccnomosColors.muted),
            ),
            const SizedBox(height: 8),
            for (final m in widget.members)
              RadioListTile<String>(
                value: (m['id'] ?? '').toString(),
                groupValue: _keepId,
                contentPadding: EdgeInsets.zero,
                title: Text((m['name'] ?? 'Unnamed').toString()),
                subtitle: ((m['vrn'] ?? '').toString().isNotEmpty ||
                        (m['email'] ?? '').toString().isNotEmpty)
                    ? Text([
                        if ((m['vrn'] ?? '').toString().isNotEmpty)
                          'VAT ${(m['vrn'] ?? '').toString()}',
                        if ((m['email'] ?? '').toString().isNotEmpty)
                          (m['email'] ?? '').toString(),
                      ].join(' · '))
                    : null,
                onChanged: (v) => setState(() {
                  _keepId = v ?? _keepId;
                  _name.text = m['name']?.toString() ?? _name.text;
                }),
              ),
            TextField(
              controller: _name,
              decoration: const InputDecoration(
                labelText: 'Name for the merged contact',
                border: OutlineInputBorder(),
                filled: true,
                fillColor: Colors.white,
              ),
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(_error!,
                    style: const TextStyle(
                        color: Color(0xFF8A3F06),
                        fontWeight: FontWeight.w600)),
              ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: FilledButton(
                    style: FilledButton.styleFrom(
                      backgroundColor: AccnomosColors.teal,
                      minimumSize: const Size.fromHeight(52),
                    ),
                    onPressed: widget.busy
                        ? null
                        : () {
                            if (_keepId.isEmpty) {
                              setState(() => _error =
                                  'Choose which contact to keep.');
                              return;
                            }
                            widget.onConfirm(_keepId, _name.text);
                          },
                    child: const Text('Confirm merge'),
                  ),
                ),
                const SizedBox(width: 8),
                TextButton(
                  style: TextButton.styleFrom(
                    foregroundColor: AccnomosColors.tealDark,
                    minimumSize: const Size(48, 52),
                  ),
                  onPressed: () => Navigator.of(context).pop(),
                  child: const Text('Cancel'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
