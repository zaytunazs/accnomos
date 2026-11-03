import 'package:flutter/material.dart';

import '../services/money.dart';
import '../services/runtime_client.dart';
import '../theme.dart';

/// Budget › Categories, rules and lines: the household's own spending
/// categories (`PUT /personal/categories`), the rules that sort bank lines
/// into them in order (`/personal/rules`, first match wins, reordered with
/// `POST /personal/rules/reorder`), and any bank line put in a category by
/// hand (`POST /personal/lines/{id}/category`). Business bank rules and the
/// ledger are never touched.
class HouseholdRulesScreen extends StatefulWidget {
  const HouseholdRulesScreen({super.key, required this.clientFor, this.initialTab = 0});

  final Future<RuntimeClient> Function() clientFor;
  final int initialTab;

  @override
  State<HouseholdRulesScreen> createState() => _HouseholdRulesScreenState();
}

class _HouseholdRulesScreenState extends State<HouseholdRulesScreen> {
  List<Map<String, dynamic>> _categories = const [];
  List<Map<String, dynamic>> _rules = const [];
  List<Map<String, dynamic>> _lines = const [];
  bool _loading = true;
  bool _busy = false;
  bool _onlyUnsorted = true;
  String? _error;
  String? _note;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final c = await widget.clientFor();
      final results = await Future.wait([
        c.personalCategories(),
        c.personalRules(),
        c.bankLines().catchError((_) => <Map<String, dynamic>>[]),
      ]);
      if (!mounted) return;
      setState(() {
        _categories = results[0];
        _rules = results[1];
        _lines = results[2];
      });
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Runs one change, shows [done] (or the runtime's refusal) and reloads.
  Future<void> _act(Future<void> Function(RuntimeClient c) work, String done) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _note = null;
    });
    try {
      final c = await widget.clientFor();
      await work(c);
      if (!mounted) return;
      setState(() => _note = done);
      await _reload();
    } catch (e) {
      if (mounted) setState(() => _note = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String _categoryName(Object? id) {
    for (final c in _categories) {
      if (c['id'] == id) return (c['name'] ?? id).toString();
    }
    return (id ?? 'Other').toString();
  }

  List<Map<String, dynamic>> _body(List<Map<String, dynamic>> cats) =>
      [for (final c in cats) {'id': c['id'], 'name': c['name']}];

  // -- Categories --------------------------------------------------------- //

  Future<String?> _askName(String title, {String initial = ''}) {
    final ctl = TextEditingController(text: initial);
    return showDialog<String>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(title),
        content: TextField(
          controller: ctl,
          autofocus: true,
          maxLength: 40,
          decoration: const InputDecoration(labelText: 'Name'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(c, ctl.text.trim()), child: const Text('Save')),
        ],
      ),
    );
  }

  Future<void> _addCategory() async {
    final name = await _askName('New category');
    if (name == null || name.isEmpty) return;
    await _act((c) => c.savePersonalCategories([..._body(_categories), {'name': name}]),
        'Added the category $name.');
  }

  Future<void> _renameCategory(Map<String, dynamic> cat) async {
    final name = await _askName('Rename category', initial: '${cat['name'] ?? ''}');
    if (name == null || name.isEmpty || name == cat['name']) return;
    final list = [
      for (final c in _body(_categories)) c['id'] == cat['id'] ? {...c, 'name': name} : c,
    ];
    await _act((c) => c.savePersonalCategories(list), 'Renamed to $name.');
  }

  Future<void> _removeCategory(Map<String, dynamic> cat) async {
    final list = [for (final c in _body(_categories)) if (c['id'] != cat['id']) c];
    await _act((c) => c.savePersonalCategories(list), 'Removed ${cat['name']}.');
  }

  Widget _categoriesTab() {
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 88),
      children: [
        const Text('Money out on your bank lines goes into these. "Other" stays for anything the rules do not recognise.',
            style: TextStyle(color: AccnomosColors.muted, height: 1.4)),
        const SizedBox(height: 8),
        for (final cat in _categories)
          Card(
            margin: const EdgeInsets.only(bottom: 8),
            child: ListTile(
              title: Text('${cat['name'] ?? ''}', style: const TextStyle(fontWeight: FontWeight.w700)),
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  IconButton(
                    tooltip: 'Rename',
                    icon: const Icon(Icons.edit_outlined),
                    onPressed: _busy ? null : () => _renameCategory(cat),
                  ),
                  if (cat['id'] != 'other')
                    IconButton(
                      tooltip: 'Remove',
                      icon: const Icon(Icons.delete_outline),
                      onPressed: _busy ? null : () => _removeCategory(cat),
                    ),
                ],
              ),
            ),
          ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          key: const Key('add-category'),
          style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(48)),
          icon: const Icon(Icons.add_outlined),
          label: const Text('Add a category'),
          onPressed: _busy ? null : _addCategory,
        ),
      ],
    );
  }

  // -- Rules -------------------------------------------------------------- //

  Future<void> _addRule({String value = ''}) async {
    final rule = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _RuleSheet(categories: _categories, initialValue: value),
    );
    if (rule == null) return;
    final value0 = (rule['match'] as Map)['value'];
    await _act((c) => c.addPersonalRule(rule),
        'Payments containing "$value0" now go to ${_categoryName(rule['category_id'])}.');
  }

  Future<void> _reorder(int oldIndex, int newIndex) async {
    final list = [..._rules];
    if (newIndex > oldIndex) newIndex -= 1;
    final moved = list.removeAt(oldIndex);
    list.insert(newIndex, moved);
    setState(() => _rules = list);
    await _act((c) => c.reorderPersonalRules([for (final r in list) '${r['id']}']), 'Rule order saved.');
  }

  String _ruleText(Map<String, dynamic> r) {
    final m = r['match'] is Map ? r['match'] as Map : const {};
    final op = '${m['op'] ?? 'contains'}';
    final words = {'contains': 'contains', 'equals': 'is exactly', 'regex': 'matches'}[op] ?? op;
    return 'Description $words "${m['value'] ?? ''}"';
  }

  Widget _rulesTab() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
          child: Text(
            _rules.isEmpty
                ? 'No rules yet. Add your own, or start with common UK shops and bills.'
                : 'Checked from the top; the first rule that matches decides. Drag to change the order.',
            style: const TextStyle(color: AccnomosColors.muted, height: 1.4),
          ),
        ),
        Expanded(
          child: ReorderableListView(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
            onReorder: _busy ? (a, b) {} : _reorder,
            children: [
              for (var i = 0; i < _rules.length; i++)
                Card(
                  key: ValueKey('rule-${_rules[i]['id']}'),
                  margin: const EdgeInsets.only(bottom: 8),
                  child: ListTile(
                    leading: ReorderableDragStartListener(
                      index: i,
                      child: const Icon(Icons.drag_indicator),
                    ),
                    title: Text(_ruleText(_rules[i])),
                    subtitle: Text('→ ${_categoryName(_rules[i]['category_id'])}',
                        style: const TextStyle(color: AccnomosColors.tealDark, fontWeight: FontWeight.w600)),
                    trailing: IconButton(
                      tooltip: 'Delete rule',
                      icon: const Icon(Icons.delete_outline),
                      onPressed: _busy
                          ? null
                          : () => _act((c) => c.deletePersonalRule('${_rules[i]['id']}'), 'Rule deleted.'),
                    ),
                  ),
                ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  key: const Key('add-rule'),
                  style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
                  icon: const Icon(Icons.add_outlined),
                  label: const Text('Add a rule'),
                  onPressed: _busy || _categories.isEmpty ? null : _addRule,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton(
                  key: const Key('starter-rules'),
                  style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(48)),
                  onPressed: _busy
                      ? null
                      : () async {
                          var added = 0;
                          await _act((c) async => added = (await c.addStarterPersonalRules()).length, '');
                          if (mounted) {
                            setState(() => _note = added == 0
                                ? 'The starter rules are already there.'
                                : 'Added $added starter ${added == 1 ? 'rule' : 'rules'}.');
                          }
                        },
                  child: const Text('Add starter rules'),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  // -- Lines -------------------------------------------------------------- //

  Future<void> _setCategory(Map<String, dynamic> line) async {
    final picked = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (c) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: Text('${line['description'] ?? ''}',
                  style: const TextStyle(fontWeight: FontWeight.w700)),
            ),
            for (final cat in _categories)
              ListTile(
                title: Text('${cat['name']}'),
                trailing: cat['id'] == line['household_category_id'] ? const Icon(Icons.check) : null,
                onTap: () => Navigator.pop(c, '${cat['id']}'),
              ),
            if (line['household_source'] == 'hand')
              ListTile(
                leading: const Icon(Icons.undo_outlined),
                title: const Text('Let the rules decide again'),
                onTap: () => Navigator.pop(c, ''),
              ),
          ],
        ),
      ),
    );
    if (picked == null) return;
    final id = '${line['id']}';
    await _act((c) => c.setLineCategory(id, picked.isEmpty ? null : picked),
        picked.isEmpty ? 'Handed back to the rules.' : 'Put in ${_categoryName(picked)}.');
  }

  Widget _linesTab() {
    final out = [
      for (final l in _lines)
        if ((l['amount_pence'] is num ? l['amount_pence'] as num : 0) < 0) l,
    ]..sort((a, b) => '${b['date'] ?? ''}'.compareTo('${a['date'] ?? ''}'));
    final unsorted = [for (final l in out) if (l['household_sorted'] == false) l];
    final shown = (_onlyUnsorted ? unsorted : out).take(200).toList();
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 88),
      children: [
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: Text('Only lines with no category (${unsorted.length})'),
          value: _onlyUnsorted,
          onChanged: (v) => setState(() => _onlyUnsorted = v),
        ),
        if (shown.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 16),
            child: Text(
              _onlyUnsorted ? 'Every line has a category.' : 'No money out on your bank lines yet.',
              style: const TextStyle(color: AccnomosColors.muted),
            ),
          ),
        for (final l in shown)
          Card(
            margin: const EdgeInsets.only(bottom: 8),
            child: ListTile(
              title: Text('${l['description'] ?? ''}', maxLines: 2, overflow: TextOverflow.ellipsis),
              subtitle: Text(
                '${l['date'] ?? ''} · ${l['household_sorted'] == false ? 'No category yet' : (l['household_category'] ?? 'Other')}'
                '${l['household_source'] == 'hand' ? ' (set by you)' : ''}',
                style: TextStyle(
                    color: l['household_sorted'] == false ? const Color(0xFF8A470D) : AccnomosColors.muted),
              ),
              trailing: Text(formatMoneyPence((l['amount_pence'] as num).abs().toInt()),
                  style: const TextStyle(fontWeight: FontWeight.w700)),
              onTap: _busy ? null : () => _setCategory(l),
            ),
          ),
        if (out.isNotEmpty)
          TextButton(
            onPressed: _busy || out.isEmpty ? null : () => _addRule(value: _ruleWord(shown.isEmpty ? out.first : shown.first)),
            child: const Text('Make a rule from a line instead'),
          ),
      ],
    );
  }

  /// The first word of a description, as a starting point for a rule.
  static String _ruleWord(Map<String, dynamic> line) {
    final words = '${line['description'] ?? ''}'.trim().split(RegExp(r'\s+'));
    return words.isEmpty ? '' : words.first;
  }

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 3,
      initialIndex: widget.initialTab.clamp(0, 2),
      child: Scaffold(
        backgroundColor: AccnomosColors.ground,
        appBar: AppBar(
          title: const Text('Categories and rules'),
          bottom: const TabBar(tabs: [
            Tab(text: 'Categories'),
            Tab(text: 'Rules'),
            Tab(text: 'Lines'),
          ]),
        ),
        body: _loading && _categories.isEmpty
            ? const Center(child: CircularProgressIndicator())
            : _error != null && _categories.isEmpty
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(mainAxisSize: MainAxisSize.min, children: [
                        Text(_error!, textAlign: TextAlign.center),
                        const SizedBox(height: 12),
                        FilledButton(onPressed: _reload, child: const Text('Try again')),
                      ]),
                    ),
                  )
                : Column(
                    children: [
                      if (_note != null && _note!.isNotEmpty)
                        Container(
                          width: double.infinity,
                          color: AccnomosColors.tealTint,
                          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                          child: Semantics(
                            liveRegion: true,
                            child: Text(_note!, key: const Key('rules-note'),
                                style: const TextStyle(color: AccnomosColors.tealDark, fontWeight: FontWeight.w600)),
                          ),
                        ),
                      Expanded(
                        child: TabBarView(children: [_categoriesTab(), _rulesTab(), _linesTab()]),
                      ),
                    ],
                  ),
      ),
    );
  }
}

class _RuleSheet extends StatefulWidget {
  const _RuleSheet({required this.categories, this.initialValue = ''});

  final List<Map<String, dynamic>> categories;
  final String initialValue;

  @override
  State<_RuleSheet> createState() => _RuleSheetState();
}

class _RuleSheetState extends State<_RuleSheet> {
  late final _value = TextEditingController(text: widget.initialValue);
  String _op = 'contains';
  String? _category;
  String? _error;

  @override
  void initState() {
    super.initState();
    final first = widget.categories.where((c) => c['id'] != 'other');
    _category = '${(first.isEmpty ? widget.categories.first : first.first)['id']}';
  }

  @override
  void dispose() {
    _value.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.of(context).viewInsets.bottom),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text('New spending rule', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _op,
            decoration: const InputDecoration(labelText: 'When the description'),
            items: const [
              DropdownMenuItem(value: 'contains', child: Text('contains')),
              DropdownMenuItem(value: 'equals', child: Text('is exactly')),
            ],
            onChanged: (v) => setState(() => _op = v ?? 'contains'),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _value,
            autofocus: widget.initialValue.isEmpty,
            decoration: const InputDecoration(labelText: 'Words, e.g. "Tesco" or "Costa"'),
          ),
          const SizedBox(height: 10),
          DropdownButtonFormField<String>(
            initialValue: _category,
            decoration: const InputDecoration(labelText: 'Put it in'),
            items: [
              for (final c in widget.categories)
                DropdownMenuItem(value: '${c['id']}', child: Text('${c['name']}')),
            ],
            onChanged: (v) => setState(() => _category = v),
          ),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(_error!, style: const TextStyle(color: Color(0xFF8A3F06))),
          ],
          const SizedBox(height: 12),
          FilledButton(
            style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
            onPressed: () {
              final value = _value.text.trim();
              if (value.isEmpty || _category == null) {
                setState(() => _error = 'Type the words to look for.');
                return;
              }
              Navigator.pop(context, {
                'match': {'op': _op, 'value': value},
                'category_id': _category,
              });
            },
            child: const Text('Save rule'),
          ),
        ],
      ),
    );
  }
}
