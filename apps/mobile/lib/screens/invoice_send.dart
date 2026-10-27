import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/books.dart';
import '../services/settings.dart';
import '../theme.dart';

/// "Send via Outlook" from `POST /invoices/{number}/send`. Nothing is sent
/// until the user confirms in the dialog below; the runtime posts
/// `confirm: true` only from that tap.
Future<Map<String, dynamic>?> confirmAndSend(
  BuildContext context, {
  required AppSettings settings,
  required AuthService auth,
  required Account? account,
  required String number,
}) async {
  // Preview first: the email draft starts from the runtime's response.
  late Map<String, dynamic> pdf;
  try {
    final client = await booksClient(settings, auth, account);
    pdf = await client.invoicePdf(number);
  } catch (e) {
    if (!context.mounted) return null;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(friendly(e))),
    );
    return null;
  }
  final email = pdf['email'] is Map
      ? Map<String, dynamic>.from(pdf['email'] as Map)
      : <String, dynamic>{};
  final problems = [
    if (pdf['problems'] is List)
      for (final p in (pdf['problems'] as List)) p.toString(),
  ];
  if (!context.mounted) return null;
  final draft = await showDialog<Map<String, String>>(
    context: context,
    builder: (_) => _SendDialog(
      to: (email['to'] ?? '').toString(),
      subject: (email['subject'] ?? '').toString(),
      body: (email['body'] ?? '').toString(),
      problems: problems,
    ),
  );
  if (draft == null || !context.mounted) return null;
  // The send step needs Mail.Send, asked for here — never at sign-in.
  try {
    final token = await auth.tokenFor(AuthService.mailSendScopes);
    final client = await booksClient(settings, auth, account,
        graphToken: token);
    final sent = await client.sendInvoice(
      number,
      confirm: true,
      to: draft['to']!.isEmpty ? null : draft['to'],
      subject: draft['subject'],
      body: draft['body'],
    );
    if (!context.mounted) return null;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
          content: Text(
              'Invoice $number sent to ${sent['sent_to'] ?? draft['to']}.')),
    );
    return sent;
  } catch (e) {
    if (!context.mounted) return null;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(friendly(e))),
    );
    return null;
  }
}

/// Confirmation dialog: who gets the invoice and what it says. The Send
/// button is the user's confirmation; cancelling sends nothing.
class _SendDialog extends StatefulWidget {
  const _SendDialog({
    required this.to,
    required this.subject,
    required this.body,
    required this.problems,
  });

  final String to;
  final String subject;
  final String body;
  final List<String> problems;

  @override
  State<_SendDialog> createState() => _SendDialogState();
}

class _SendDialogState extends State<_SendDialog> {
  late final TextEditingController _to;
  late final TextEditingController _subject;
  late final TextEditingController _body;
  bool _sending = false;

  @override
  void initState() {
    super.initState();
    _to = TextEditingController(text: widget.to);
    _subject = TextEditingController(text: widget.subject);
    _body = TextEditingController(text: widget.body);
  }

  @override
  void dispose() {
    _to.dispose();
    _subject.dispose();
    _body.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final blocked = widget.problems.isNotEmpty;
    return AlertDialog(
      title: const Text('Send via Outlook'),
      content: SizedBox(
        width: double.maxFinite,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (blocked)
                Container(
                  margin: const EdgeInsets.only(bottom: 12),
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFFF7ED),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                        color: const Color(0xFFF3C892)),
                  ),
                  child: Text(
                    widget.problems.join('\n'),
                    style: const TextStyle(
                        color: Color(0xFF8A3F06), height: 1.4),
                  ),
                ),
              TextField(
                controller: _to,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(
                  labelText: 'To',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _subject,
                decoration: const InputDecoration(
                  labelText: 'Subject',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _body,
                maxLines: 6,
                minLines: 4,
                decoration: const InputDecoration(
                  labelText: 'Message',
                  border: OutlineInputBorder(),
                  alignLabelWithHint: true,
                ),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed:
              _sending ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          style: FilledButton.styleFrom(
              backgroundColor: AccnomosColors.teal),
          onPressed: blocked || _sending
              ? null
              : () {
                  if (_to.text.trim().isEmpty) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                          content: Text(
                              'Add an email address first.')),
                    );
                    return;
                  }
                  setState(() => _sending = true);
                  Navigator.of(context).pop({
                    'to': _to.text.trim(),
                    'subject': _subject.text.trim(),
                    'body': _body.text,
                  });
                },
          child: const Text('Send'),
        ),
      ],
    );
  }
}
