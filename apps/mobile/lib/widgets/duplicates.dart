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
    .join('\n');

/// Suggestions shown before "Show all N".
const _collapsedCount = 3;

class _DuplicatesState extends State<DuplicatesCard> {
  bool _showAll = false;
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
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AccnomosColors.border),
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
              'Found by code from shared details or close names. '
              'Nothing merges until you choose.',
              style:
                  TextStyle(fontSize: 13, color: AccnomosColors.muted),
            ),
            const SizedBox(height: 12),
            for (final g in _showAll ? widget.groups : widget.groups.take(_collapsedCount))
              _GroupTile(
                group: g,
                busy: _busy != null,
                merging: _busy == 'merge:${_groupKey(g)}',
                dismissing: _busy == _groupKey(g),
                onMerge: () => _openMerge(g),
                onDismiss: () => _dismiss(g),
              ),
            if (widget.groups.length > _collapsedCount)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton(
                  style: TextButton.styleFrom(
                    foregroundColor: AccnomosColors.tealDark,
                    minimumSize: const Size(48, 44),
                  ),
                  onPressed: () => setState(() => _showAll = !_showAll),
                  child: Text(_showAll
                      ? 'Show fewer'
                      : 'Show all ${widget.groups.length}'),
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
            RadioGroup<String>(
              groupValue: _keepId,
              onChanged: (v) {
                if (v == null) return;
                final picked = widget.members.firstWhere(
                  (c) => (c['id'] ?? '').toString() == v,
                  orElse: () => const <String, dynamic>{},
                );
                setState(() {
                  _keepId = v;
                  final name = (picked['name'] ?? '').toString();
                  if (name.isNotEmpty) _name.text = name;
                });
              },
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  for (final m in widget.members)
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title:
                          Text((m['name'] ?? 'Unnamed').toString()),
                      subtitle: ((m['vrn'] ?? '').toString().isNotEmpty ||
                              (m['email'] ?? '').toString().isNotEmpty)
                          ? Text([
                              if ((m['vrn'] ?? '').toString().isNotEmpty)
                                'VAT ${(m['vrn'] ?? '').toString()}',
                              if ((m['email'] ?? '').toString().isNotEmpty)
                                (m['email'] ?? '').toString(),
                            ].join(' · '))
                          : null,
                      leading: Radio<String>(
                          value: (m['id'] ?? '').toString()),
                    ),
                ],
              ),
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

/// One suggestion as its own small card: why code thinks so, each contact on its own row, the AI's view when there is
/// one, then Merge… and Not duplicates. Never a run-on line of names.
class _GroupTile extends StatelessWidget {
  const _GroupTile({
    required this.group,
    required this.busy,
    required this.merging,
    required this.dismissing,
    required this.onMerge,
    required this.onDismiss,
  });

  final Map<String, dynamic> group;
  final bool busy;
  final bool merging;
  final bool dismissing;
  final VoidCallback onMerge;
  final VoidCallback onDismiss;

  static String _kind(String k) => switch (k) {
        'customer' => 'Customer',
        'supplier' => 'Supplier',
        'both' => 'Customer and supplier',
        _ => k.isEmpty ? '' : '${k[0].toUpperCase()}${k.substring(1)}',
      };

  @override
  Widget build(BuildContext context) {
    final members = _groupMembers(group);
    final evidence = [
      for (final e in ((group['evidence'] as List?) ?? const [])) e.toString(),
    ];
    final reason = (group['reason'] ?? '').toString().trim();
    final lead = reason.isNotEmpty ? reason : (evidence.isEmpty ? '' : evidence.first);
    final blocked = group['blocked'] == true;
    final ai = group['ai'] is Map ? Map<String, dynamic>.from(group['ai']) : null;
    final aiText = duplicateAiText(ai, blocked);
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 8),
      decoration: BoxDecoration(
        color: AccnomosColors.ground,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AccnomosColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (lead.isNotEmpty)
            Text(
              lead[0].toUpperCase() + lead.substring(1),
              style: const TextStyle(
                  fontSize: 13, fontWeight: FontWeight.w600, color: AccnomosColors.tealDark),
            ),
          const SizedBox(height: 6),
          for (final m in members)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(top: 2, right: 8),
                    child: Icon(Icons.person_outline, size: 18, color: AccnomosColors.muted),
                  ),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          (m['name'] ?? 'Unnamed').toString(),
                          style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
                        ),
                        Builder(builder: (_) {
                          final details = [
                            _kind((m['kind'] ?? '').toString()),
                            if ((m['email'] ?? '').toString().isNotEmpty) (m['email'] ?? '').toString(),
                            if ((m['vrn'] ?? '').toString().isNotEmpty) 'VAT ${(m['vrn'] ?? '').toString()}',
                          ].where((t) => t.isNotEmpty).join(' · ');
                          return details.isEmpty
                              ? const SizedBox.shrink()
                              : Text(details,
                                  style: const TextStyle(fontSize: 13, color: AccnomosColors.muted));
                        }),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          if (aiText != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(aiText, style: const TextStyle(fontSize: 13, color: AccnomosColors.muted)),
            ),
          const SizedBox(height: 6),
          Wrap(
            spacing: 8,
            runSpacing: 4,
            children: [
              if (!blocked)
                FilledButton(
                  style: FilledButton.styleFrom(
                    backgroundColor: AccnomosColors.teal,
                    minimumSize: const Size(96, 44),
                  ),
                  onPressed: busy ? null : onMerge,
                  child: Text(merging ? 'Merging…' : 'Merge…'),
                ),
              OutlinedButton(
                style: OutlinedButton.styleFrom(
                  foregroundColor: AccnomosColors.tealDark,
                  minimumSize: const Size(96, 44),
                ),
                onPressed: busy ? null : onDismiss,
                child: Text(dismissing ? 'Saving…' : 'Not duplicates'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
