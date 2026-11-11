import 'package:flutter/material.dart';

import '../services/auth.dart';
import '../services/books.dart' show booksClient;
import '../services/device_facts.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';

/// More › Report a problem: a message, sent with the app version and the
/// phone type to `POST /bug-reports` (docs/billing/PLANS_AND_CONTRACT.md).
/// No screenshot from the app: the user can describe it, or use the web's
/// Help › Report a problem to attach one.
Future<void> showReportProblem(BuildContext context,
    {Future<String> Function(String message)? send}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => ReportProblemSheet(send: send),
  );
}

class ReportProblemSheet extends StatefulWidget {
  const ReportProblemSheet({super.key, this.send});

  /// Test seam; the real one posts through [RuntimeClient.postBugReport].
  final Future<String> Function(String message)? send;

  @override
  State<ReportProblemSheet> createState() => _ReportProblemSheetState();
}

class _ReportProblemSheetState extends State<ReportProblemSheet> {
  final _controller = TextEditingController();
  bool _busy = false;
  bool _sent = false;
  String? _error;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<String> _post(String message) async {
    final settings = await AppSettings.load();
    final auth = AuthService();
    final account = await auth.account();
    if (account == null) throw RuntimeException('Sign in first, so we can reply.');
    final client = await booksClient(settings, auth, account);
    final facts = DeviceFacts();
    return client.postBugReport(
      message: message,
      page: 'android:more',
      version: await facts.appVersion(),
      ua: await facts.userAgent(),
    );
  }

  Future<void> _submit() async {
    final message = _controller.text.trim();
    if (message.length < 5) {
      setState(() => _error = 'Tell us a little about what went wrong.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await (widget.send ?? _post)(message);
      if (mounted) setState(() => _sent = true);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(
          16, 0, 16, MediaQuery.of(context).viewInsets.bottom + 16),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Report a problem',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
            const SizedBox(height: 12),
            if (_sent) ...[
              const Text('Thank you. We have your report and will look at it.',
                  key: Key('report-sent')),
              const SizedBox(height: 12),
              FilledButton(
                  onPressed: () => Navigator.of(context).pop(),
                  child: const Text('Close')),
            ] else ...[
              TextField(
                key: const Key('report-message'),
                controller: _controller,
                minLines: 4,
                maxLines: 8,
                maxLength: 4000,
                decoration: const InputDecoration(
                    labelText: 'What went wrong?',
                    border: OutlineInputBorder()),
              ),
              const Text(
                  'We send your message, the app version and your phone type. Nothing else.',
                  style: TextStyle(color: AccnomosColors.muted, fontSize: 12)),
              if (_error != null) ...[
                const SizedBox(height: 8),
                Text(_error!,
                    key: const Key('report-error'),
                    style: const TextStyle(
                        color: Colors.red, fontWeight: FontWeight.w700)),
              ],
              const SizedBox(height: 12),
              FilledButton(
                key: const Key('report-send'),
                onPressed: _busy ? null : _submit,
                child: Text(_busy ? 'Sending…' : 'Send report'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
