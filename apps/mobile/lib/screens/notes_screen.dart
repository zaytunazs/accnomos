import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/books.dart' show booksClient;
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/loading.dart';

/// Builds the runtime client for the Notes screen; tests inject a fake.
typedef NotesClientFactory = RuntimeClient Function(AppSettings settings);

/// One saved note (`GET /notes`).
class Note {
  const Note({required this.id, required this.text, this.due, this.spoken = false, this.created});

  factory Note.fromJson(Map<String, dynamic> j) => Note(
        id: (j['id'] ?? '').toString(),
        text: (j['text'] ?? '').toString(),
        due: DateTime.tryParse('${j['due']}'),
        spoken: j['source'] == 'voice',
        created: DateTime.tryParse('${j['created']}'),
      );

  final String id;
  final String text;
  final DateTime? due;
  final bool spoken;
  final DateTime? created;
}

const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
String _day(DateTime d) {
  final l = d.toLocal();
  return '${l.day} ${_months[l.month - 1]}';
}

/// Notes: quick notes typed here or said to the assistant ("take a note:
/// call the plumber back"), kept in the books (`_System/notes/notes.json`).
/// Delete asks first.
class NotesScreen extends StatefulWidget {
  const NotesScreen({
    super.key,
    this.clientFactory,
    @visibleForTesting this.testAccount,
    @visibleForTesting this.testAccountReady = false,
  });

  final NotesClientFactory? clientFactory;
  @visibleForTesting
  final Account? testAccount;
  @visibleForTesting
  final bool testAccountReady;

  @override
  State<NotesScreen> createState() => _NotesScreenState();
}

class _NotesScreenState extends State<NotesScreen> {
  final AuthService _auth = AuthService();
  final TextEditingController _text = TextEditingController();
  AppSettings? _settings;
  Account? _account;
  bool _checked = false;
  bool _busy = false;
  String? _error;
  List<Note>? _notes;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final settings = await AppSettings.load();
    Account? account;
    if (widget.testAccountReady) {
      account = widget.testAccount;
    } else {
      try {
        account = await _auth.account();
      } catch (_) {
        account = null;
      }
    }
    if (!mounted) return;
    setState(() {
      _settings = settings;
      _account = account;
      _checked = true;
    });
    if (account != null || widget.clientFactory != null) await _reload();
  }

  Future<RuntimeClient> _client() async {
    final factory = widget.clientFactory;
    if (factory != null) return factory(_settings!);
    return booksClient(_settings!, _auth, _account);
  }

  Future<void> _reload() async {
    try {
      final rows = await (await _client()).notes();
      if (mounted) setState(() => _notes = [for (final r in rows) Note.fromJson(r)]);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    }
  }

  Future<void> _act(Future<void> Function(RuntimeClient c) fn) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await fn(await _client());
      await _reload();
    } catch (e) {
      if (mounted) setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _add() async {
    final text = _text.text.trim();
    if (text.isEmpty) return;
    await _act((c) async {
      await c.addNote(text);
      _text.clear();
    });
  }

  Future<void> _delete(Note n) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete this note?'),
        content: Text(n.text),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Keep')),
          FilledButton(
            key: const ValueKey('note-delete-confirm'),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (ok == true) await _act((c) => c.deleteNote(n.id));
  }

  @override
  Widget build(BuildContext context) {
    final signedIn = _account != null || widget.clientFactory != null;
    return Scaffold(
      appBar: AppBar(title: const Text('Notes')),
      body: !_checked
          ? const Padding(padding: EdgeInsets.all(16), child: SkeletonCard())
          : !signedIn
              ? const Padding(
                  padding: EdgeInsets.all(16),
                  child: Text(
                    'Sign in to keep notes. Notes you type here or say to the assistant are kept in your OneDrive with your books.',
                  ),
                )
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: TextField(
                            key: const ValueKey('note-text'),
                            controller: _text,
                            maxLength: 500,
                            decoration: const InputDecoration(hintText: 'Write a note…', counterText: ''),
                            onSubmitted: (_) => _add(),
                          ),
                        ),
                        const SizedBox(width: 8),
                        FilledButton(
                          key: const ValueKey('note-save'),
                          onPressed: _busy ? null : _add,
                          child: const Text('Save'),
                        ),
                      ],
                    ),
                    if (_error != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 12),
                        child: Text(_error!, style: const TextStyle(color: AccnomosColors.warnText)),
                      ),
                    const SizedBox(height: 12),
                    if (_notes == null && _error == null)
                      const SkeletonCard()
                    else if ((_notes ?? const []).isEmpty)
                      const Text(
                        'No notes yet. Type one above, or tell the assistant “take a note: …”.',
                        style: TextStyle(color: AccnomosColors.muted),
                      )
                    else
                      for (final n in _notes!)
                        Card(
                          child: ListTile(
                            title: Text(n.text),
                            subtitle: Text([
                              if (n.created != null) _day(n.created!),
                              if (n.spoken) 'spoken',
                              if (n.due != null) 'due ${_day(n.due!)}',
                            ].join(' · ')),
                            trailing: IconButton(
                              tooltip: 'Delete note',
                              icon: const Icon(Icons.delete_outline),
                              onPressed: _busy ? null : () => _delete(n),
                            ),
                          ),
                        ),
                  ],
                ),
    );
  }
}
