import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/dashboard.dart' show shortDate;
import '../models/suggestions.dart';
import '../models/todo.dart';
import '../models/triage.dart';
import '../services/auth.dart';
import '../services/books.dart' show booksClient, friendly;
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';

/// Shared card shell for the Home extras: white, rounded, labelled.
class HomeCard extends StatelessWidget {
  const HomeCard({
    super.key,
    required this.label,
    required this.child,
    this.sampled = false,
  });

  final String label;
  final Widget child;

  /// True renders the "SAMPLE — FICTIONAL COMPANY" tag above the content.
  final bool sampled;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label.toUpperCase(),
              style: const TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: AccnomosColors.muted,
                  letterSpacing: 0.6)),
          if (sampled) ...[
            const SizedBox(height: 6),
            Container(
              padding:
                  const EdgeInsets.symmetric(vertical: 3, horizontal: 8),
              decoration: BoxDecoration(
                color: AccnomosColors.ink,
                borderRadius: BorderRadius.circular(6),
              ),
              child: const Text(
                'SAMPLE — FICTIONAL COMPANY',
                style: TextStyle(
                    color: AccnomosColors.ground,
                    fontSize: 10,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 0.5),
              ),
            ),
          ],
          const SizedBox(height: 8),
          child,
        ],
      ),
    );
  }
}

/// Home › To-dos: the list in `_System/Todos/todos.json` with tick-to-delete
/// and a quick-add field, plus code-built suggestions from the dashboard
/// payload. Signed out: labelled fictional samples.
class TodosCard extends StatefulWidget {
  const TodosCard({
    super.key,
    required this.settings,
    required this.auth,
    required this.account,
    this.suggestions = const [],
    this.onOpen,
    this.refresh = 0,
  });

  final AppSettings settings;
  final AuthService auth;

  /// Null when nobody is signed in: the card shows samples and never calls.
  final Account? account;

  /// Code-built lines from the dashboard ("3 receipts to review").
  final List<HomeSuggestion> suggestions;

  /// Opens the screen a suggestion points at.
  final void Function(SuggestionTarget target)? onOpen;

  /// Bumped by Home's pull-to-refresh so the list reloads too.
  final int refresh;

  @override
  State<TodosCard> createState() => _TodosCardState();
}

class _TodosCardState extends State<TodosCard> {
  final TextEditingController _add = TextEditingController();
  List<TodoItem>? _todos;
  bool _loading = false;
  bool _adding = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    if (widget.account != null) _load();
  }

  @override
  void didUpdateWidget(TodosCard old) {
    super.didUpdateWidget(old);
    if (widget.account != null &&
        (old.account == null || widget.refresh != old.refresh)) {
      _load();
    }
  }

  @override
  void dispose() {
    _add.dispose();
    super.dispose();
  }

  Future<RuntimeClient?> _client() async {
    final account = widget.account;
    if (account == null) return null;
    try {
      return await booksClient(widget.settings, widget.auth, account);
    } catch (e) {
      if (mounted) setState(() => _error = friendly(e));
      return null;
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final client = await _client();
      if (!mounted || client == null) return;
      final raw = await client.todos();
      if (!mounted) return;
      setState(() => _todos = TodoItem.listFromJson(raw));
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _addTodo() async {
    final text = _add.text.trim();
    if (widget.account == null || text.isEmpty || _adding) return;
    setState(() {
      _adding = true;
      _error = null;
    });
    try {
      final client = await _client();
      if (!mounted || client == null) return;
      await client.addTodo(text);
      _add.clear();
      final raw = await client.todos();
      if (!mounted) return;
      setState(() => _todos = TodoItem.listFromJson(raw));
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _adding = false);
    }
  }

  Future<void> _done(TodoItem todo) async {
    if (widget.account == null) return;
    final client = await _client();
    if (client == null || !mounted) return;
    final kept = _todos;
    setState(() => _todos = kept?.where((t) => t.id != todo.id).toList());
    try {
      await client.deleteTodo(todo.id);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _todos = kept;
        _error = friendly(e);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.account == null) {
      return HomeCard(
        label: 'To-dos',
        sampled: true,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (final t in TodoItem.samples) _sampleRow(t),
            const SizedBox(height: 4),
            const Text(
              'Sign in to keep your own to-do list.',
              style: TextStyle(color: AccnomosColors.muted, fontSize: 12),
            ),
          ],
        ),
      );
    }
    final todos = _todos;
    return HomeCard(
      label: 'To-dos',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_loading && todos == null)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Center(
                  child: SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2))),
            )
          else if (todos == null || todos.isEmpty)
            const Text(
              'Nothing on your list.',
              style: TextStyle(color: AccnomosColors.muted, fontSize: 13),
            )
          else
            for (final t in todos.take(5)) _todoRow(t),
          if (todos != null && todos.length > 5)
            Text('and ${todos.length - 5} more',
                style: const TextStyle(
                    color: AccnomosColors.muted, fontSize: 12)),
          if (widget.suggestions.isNotEmpty) ...[
            const SizedBox(height: 8),
            for (final s in widget.suggestions)
              InkWell(
                onTap: widget.onOpen == null
                    ? null
                    : () => widget.onOpen!(s.target),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(
                    children: [
                      const Icon(Icons.arrow_right_outlined,
                          size: 20, color: AccnomosColors.tealDark),
                      Expanded(
                        child: Text(s.text,
                            style: const TextStyle(
                                fontWeight: FontWeight.w700,
                                color: AccnomosColors.ink,
                                fontSize: 13)),
                      ),
                    ],
                  ),
                ),
              ),
          ],
          if (_error != null) ...[
            const SizedBox(height: 6),
            Text(_error!,
                style: const TextStyle(
                    color: Color(0xFF8A3F06), fontSize: 12, height: 1.4)),
          ],
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _add,
                  textInputAction: TextInputAction.done,
                  onSubmitted: (_) => _addTodo(),
                  decoration: const InputDecoration(
                    hintText: 'Add a to-do…',
                    border: OutlineInputBorder(),
                    isDense: true,
                    contentPadding:
                        EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              FilledButton(
                style: FilledButton.styleFrom(
                    backgroundColor: AccnomosColors.teal,
                    minimumSize: const Size(48, 44),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12))),
                onPressed: _adding ? null : _addTodo,
                child: _adding
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white))
                    : const Text('Add',
                        style: TextStyle(fontWeight: FontWeight.w800)),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _sampleRow(TodoItem todo) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.check_box_outline_blank_outlined,
              size: 20, color: AccnomosColors.muted),
          const SizedBox(width: 8),
          Expanded(
            child: Text(todo.text,
                style:
                    const TextStyle(color: AccnomosColors.ink, fontSize: 13)),
          ),
        ],
      ),
    );
  }

  Widget _todoRow(TodoItem todo) {
    return InkWell(
      onTap: () => _done(todo),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 40,
              height: 40,
              child: Checkbox(
                value: false,
                onChanged: (_) => _done(todo),
                activeColor: AccnomosColors.teal,
              ),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.only(top: 9),
                child: Text.rich(
                  TextSpan(
                    text: todo.text,
                    style: const TextStyle(
                        color: AccnomosColors.ink, fontSize: 13),
                    children: [
                      if (todo.due != null)
                        TextSpan(
                          text: ' · ${shortDate(todo.due)}',
                          style: const TextStyle(
                              color: AccnomosColors.muted,
                              fontWeight: FontWeight.w700,
                              fontSize: 12),
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Home › Inbox: "Check inbox" runs `POST /mail/triage` (asking for
/// `Mail.Read` only on tap) and lists the threads needing a reply with the
/// suggested answer. "Save draft in Outlook" stores the reply as a draft
/// after a confirmation sheet showing the exact text — nothing is ever sent
/// from the phone. Signed out: labelled fictional samples.
class InboxCard extends StatefulWidget {
  const InboxCard({
    super.key,
    required this.settings,
    required this.auth,
    required this.account,
  });

  final AppSettings settings;
  final AuthService auth;

  /// Null when nobody is signed in: the card shows samples and never calls.
  final Account? account;

  @override
  State<InboxCard> createState() => _InboxCardState();
}

class _InboxCardState extends State<InboxCard> {
  List<TriageThread>? _threads;
  int _otherCount = 0;
  bool _checking = false;
  bool _checked = false;
  String? _error;
  final Set<String> _savedDrafts = {};
  final Set<String> _open = {};

  Future<void> _check() async {
    if (_checking) return;
    setState(() {
      _checking = true;
      _error = null;
    });
    try {
      // Mail.Read is asked for here — never at sign-in.
      final token = await widget.auth.tokenFor(AuthService.mailReadScopes);
      final client = await booksClient(
          widget.settings, widget.auth, widget.account,
          graphToken: token);
      final result = await client.mailTriage();
      if (!mounted) return;
      final threads =
          TriageThread.listFromJson(result['threads']);
      setState(() {
        _threads = threads.where((t) => t.needsReply).toList();
        _otherCount = threads.length - _threads!.length;
        _checked = true;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  Future<void> _confirmAndSave(TriageThread thread) async {
    final controller =
        TextEditingController(text: thread.suggestedReply ?? '');
    final confirmed = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      builder: (sheet) => Padding(
        padding: EdgeInsets.only(
            left: 20,
            right: 20,
            top: 20,
            bottom: MediaQuery.of(sheet).viewInsets.bottom + 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Save draft in Outlook',
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 4),
            Text('To answer ${thread.who} — ${thread.subject}',
                style: const TextStyle(
                    color: AccnomosColors.muted, fontSize: 12)),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              maxLines: 6,
              minLines: 4,
              maxLength: 5000,
              decoration: const InputDecoration(
                labelText: 'The exact reply to save as a draft',
                border: OutlineInputBorder(),
                alignLabelWithHint: true,
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              'Nothing is sent: the reply waits in your Outlook Drafts '
              'for you to send.',
              style:
                  TextStyle(color: AccnomosColors.muted, fontSize: 12),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(
                        minimumSize: const Size.fromHeight(48),
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14))),
                    onPressed: () => Navigator.of(sheet).pop(),
                    child: const Text('Cancel'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: FilledButton(
                    style: FilledButton.styleFrom(
                        backgroundColor: AccnomosColors.teal,
                        minimumSize: const Size.fromHeight(48),
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14))),
                    onPressed: () {
                      if (controller.text.trim().isEmpty) return;
                      Navigator.of(sheet).pop(controller.text);
                    },
                    child: const Text('Save draft',
                        style: TextStyle(fontWeight: FontWeight.w800)),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
    controller.dispose();
    if (confirmed == null || !mounted) return;
    try {
      // Mail.ReadWrite is asked for here — never at sign-in.
      final token =
          await widget.auth.tokenFor(AuthService.mailReadWriteScopes);
      final client = await booksClient(
          widget.settings, widget.auth, widget.account,
          graphToken: token);
      await client.draftReply(thread.messageId, confirmed);
      if (!mounted) return;
      setState(() => _savedDrafts.add(thread.messageId));
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
            content: Text(
                'Draft saved in Outlook. Send it from there — '
                'nothing was sent from this phone.')),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = friendly(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.account == null) {
      return HomeCard(
        label: 'Inbox',
        sampled: true,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (final t in TriageThread.samples) _sampleThread(t),
            const SizedBox(height: 4),
            const Text(
              'Sign in to check your inbox.',
              style: TextStyle(color: AccnomosColors.muted, fontSize: 12),
            ),
          ],
        ),
      );
    }
    final threads = _threads;
    return HomeCard(
      label: 'Inbox',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (threads == null) ...[
            const Text(
              'Business threads from the last 7 days, with a suggested '
              'reply for each one needing an answer.',
              style:
                  TextStyle(color: AccnomosColors.muted, fontSize: 12, height: 1.4),
            ),
            const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                style: FilledButton.styleFrom(
                    backgroundColor: AccnomosColors.teal,
                    minimumSize: const Size.fromHeight(48),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(14))),
                onPressed: _checking ? null : _check,
                child: _checking
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white))
                    : const Text('Check inbox',
                        style: TextStyle(
                            fontWeight: FontWeight.w800, fontSize: 16)),
              ),
            ),
            const SizedBox(height: 6),
            const Text(
              'Nothing is ever sent from this phone: replies are saved '
              'as Outlook drafts for you to send.',
              textAlign: TextAlign.center,
              style: TextStyle(color: AccnomosColors.muted, fontSize: 12),
            ),
          ] else if (threads.isEmpty) ...[
            Text(
              _checked
                  ? 'Nothing needs a reply.'
                      '${_otherCount > 0 ? ' ($_otherCount other ${_otherCount == 1 ? 'thread' : 'threads'} checked.)' : ''}'
                  : 'Nothing needs a reply.',
              style: const TextStyle(
                  color: AccnomosColors.muted, fontSize: 13),
            ),
            const SizedBox(height: 8),
            OutlinedButton(
              style: OutlinedButton.styleFrom(
                  minimumSize: const Size.fromHeight(44),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12))),
              onPressed: _checking ? null : _check,
              child: const Text('Check again'),
            ),
          ] else ...[
            Text(
              '${threads.length} ${threads.length == 1 ? 'thread needs' : 'threads need'} a reply'
              '${_otherCount > 0 ? ' · $_otherCount ${_otherCount == 1 ? 'other' : 'others'} checked' : ''}',
              style: const TextStyle(
                  color: AccnomosColors.muted, fontSize: 12),
            ),
            const SizedBox(height: 4),
            for (final t in threads) _thread(t),
            const SizedBox(height: 4),
            OutlinedButton(
              style: OutlinedButton.styleFrom(
                  minimumSize: const Size.fromHeight(44),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12))),
              onPressed: _checking ? null : _check,
              child: const Text('Check again'),
            ),
            const SizedBox(height: 6),
            const Text(
              'Nothing is ever sent from this phone: replies are saved '
              'as Outlook drafts for you to send.',
              textAlign: TextAlign.center,
              style: TextStyle(color: AccnomosColors.muted, fontSize: 12),
            ),
          ],
          if (_error != null) ...[
            const SizedBox(height: 6),
            Text(_error!,
                style: const TextStyle(
                    color: Color(0xFF8A3F06), fontSize: 12, height: 1.4)),
          ],
        ],
      ),
    );
  }

  Widget _sampleThread(TriageThread thread) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(thread.who,
              style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  color: AccnomosColors.ink,
                  fontSize: 13)),
          Text(thread.summary,
              style: const TextStyle(
                  color: AccnomosColors.muted, fontSize: 12, height: 1.4)),
          if (thread.suggestedReply != null)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text('“${thread.suggestedReply}”',
                  style: const TextStyle(
                      color: AccnomosColors.ink, fontSize: 12, height: 1.4)),
            ),
        ],
      ),
    );
  }

  Widget _thread(TriageThread thread) {
    final open = _open.contains(thread.conversationId);
    final saved = _savedDrafts.contains(thread.messageId);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        InkWell(
          onTap: () => setState(() {
            if (open) {
              _open.remove(thread.conversationId);
            } else {
              _open.add(thread.conversationId);
            }
          }),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(thread.who,
                          style: const TextStyle(
                              fontWeight: FontWeight.w700,
                              color: AccnomosColors.ink,
                              fontSize: 13)),
                      Text(thread.summary,
                          maxLines: open ? null : 2,
                          overflow: open ? null : TextOverflow.ellipsis,
                          style: const TextStyle(
                              color: AccnomosColors.muted,
                              fontSize: 12,
                              height: 1.4)),
                    ],
                  ),
                ),
                const SizedBox(width: 4),
                const Text('Reply',
                    style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w800,
                        color: Color(0xFFB45309))),
                Icon(open
                    ? Icons.expand_less_outlined
                    : Icons.expand_more_outlined),
              ],
            ),
          ),
        ),
        if (open) ...[
          if (thread.fallbackReason != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(thread.fallbackReason!,
                  style: const TextStyle(
                      color: AccnomosColors.muted, fontSize: 12)),
            ),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: AccnomosColors.ground,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Text(
              thread.suggestedReply?.isNotEmpty == true
                  ? thread.suggestedReply!
                  : 'The runtime suggested no reply.',
              style: const TextStyle(
                  color: AccnomosColors.ink, fontSize: 13, height: 1.4),
            ),
          ),
          const SizedBox(height: 6),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
              style: OutlinedButton.styleFrom(
                  minimumSize: const Size.fromHeight(44),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12))),
              onPressed: saved ||
                      thread.suggestedReply?.trim().isEmpty != false
                  ? null
                  : () => _confirmAndSave(thread),
              child: Text(saved
                  ? 'Draft saved'
                  : 'Save draft in Outlook'),
            ),
          ),
        ],
        const Divider(height: 12),
      ],
    );
  }
}
