import 'package:flutter/material.dart';

import '../models/paypal.dart';
import '../services/auth.dart';
import '../services/books.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';

/// Builds the books client for the PayPal screens; null when nobody is
/// signed in (and no demo is running). Tests inject one that answers from
/// a mock transport.
typedef PayPalClientFactory = Future<RuntimeClient?> Function();

/// The real client: the signed-in account, or the demo session (the
/// runtime answers a demo with its own sample PayPal history and dispute).
Future<RuntimeClient?> defaultPayPalClient() async {
  final settings = await AppSettings.load();
  final auth = AuthService();
  final account = await auth.account();
  if (account == null) return null;
  return booksClient(settings, auth, account);
}

/// "11 Nov 2026, 14:29" in the phone's own time, from an ISO timestamp.
String ukDateTime(String iso) {
  final d = DateTime.tryParse(iso);
  if (d == null) return iso;
  final local = d.toLocal();
  final hh = local.hour.toString().padLeft(2, '0');
  final mm = local.minute.toString().padLeft(2, '0');
  return '${ukDate(isoDate(local))}, $hh:$mm';
}

/// A rounded white card, the house style of the books screens.
class PanelCard extends StatelessWidget {
  const PanelCard({super.key, required this.children, this.warn = false});

  final List<Widget> children;
  final bool warn;

  @override
  Widget build(BuildContext context) {
    // A Material (not a decorated box), so list tiles inside keep their ink.
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Material(
        color: warn ? const Color(0xFFFFF4E5) : Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: BorderSide(
              color: warn ? const Color(0xFFE8B66B) : AccnomosColors.border),
        ),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: SizedBox(
            width: double.infinity,
            child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: children),
          ),
        ),
      ),
    );
  }
}

const panelTitle = TextStyle(fontSize: 16, fontWeight: FontWeight.w800);
const panelMuted = TextStyle(color: AccnomosColors.muted, height: 1.4);
const panelWarn = TextStyle(
    color: Color(0xFF8A470D), fontWeight: FontWeight.w700, height: 1.4);

/// What approving posts: the runtime's journal lines, Dr/Cr in pounds.
class JournalPreview extends StatelessWidget {
  const JournalPreview({super.key, required this.lines});

  final List<JournalLine> lines;

  @override
  Widget build(BuildContext context) {
    if (lines.isEmpty) return const SizedBox.shrink();
    const small = TextStyle(fontSize: 13, color: AccnomosColors.ink);
    return Semantics(
      label: 'What approving posts',
      child: Padding(
        padding: const EdgeInsets.only(top: 8),
        child: Column(
          children: [
            for (final j in lines)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Text(
                          '${j.account}${j.vatCode != null ? ' (VAT ${j.vatCode})' : ''}',
                          style: small),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      j.debitPence != 0
                          ? 'Dr ${gbp(j.debitPence)}'
                          : 'Cr ${gbp(j.creditPence)}',
                      style: small.copyWith(fontWeight: FontWeight.w700),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// A plain sign-in prompt for the PayPal screens.
class PayPalSignedOut extends StatelessWidget {
  const PayPalSignedOut({super.key, required this.what});

  final String what;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text('Sign in, or try the demo, to $what.',
              textAlign: TextAlign.center),
        ),
      );
}

/// Ask before anything posts or moves money. True only on the owner's tap.
Future<bool> confirmAction(
  BuildContext context, {
  required String title,
  required String body,
  required String yes,
}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: Text(body),
      actions: [
        TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel')),
        FilledButton(
          key: const Key('confirm-yes'),
          style: FilledButton.styleFrom(backgroundColor: AccnomosColors.teal),
          onPressed: () => Navigator.of(ctx).pop(true),
          child: Text(yes),
        ),
      ],
    ),
  );
  return ok == true;
}
