import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../services/app_mode.dart';
import '../services/auth.dart';
import '../services/demo.dart';
import '../services/settings.dart';
import '../services/sign_in_messages.dart';
import '../theme.dart';
import '../widgets/brand.dart';

/// What a signed-out phone opens on: the website's landing in short
/// (apps/web/src/components/marketing/Landing.tsx). Its words are the
/// website's own: the hero, the four steps and the demo note. From here the
/// owner signs in with Microsoft, or tries the company or the personal demo
/// (a live sandbox on the runtime, services/runtime/app/demo.py).
class WelcomeScreen extends StatefulWidget {
  const WelcomeScreen({super.key, this.notice, this.signIn, this.startDemo});

  /// A short sentence to show first (a demo that timed out, for example).
  final String? notice;

  /// Tests: stand-ins for Microsoft sign-in and for starting a demo.
  final Future<void> Function()? signIn;
  final Future<void> Function(String kind)? startDemo;

  /// The four steps, word for word as the website's "How it works".
  static const steps = [
    (
      'Send it in',
      'Photograph a receipt in the Android app, upload it on the web, or let '
          'receipts arrive from your email inbox. You can also just say what you need.'
    ),
    (
      'The AI proposes',
      'A Meta model reads the document and suggests supplier, category, VAT and '
          'totals. Code checks the arithmetic.'
    ),
    (
      'You approve',
      'Each proposal waits in Review. Approve, edit or reject. Nothing posts on its own.'
    ),
    (
      'VAT and records, ready',
      'Approved entries build your ledger, your VAT boxes and a spreadsheet copy of your books.'
    ),
  ];

  static const audiences = [
    'Small businesses',
    'Sole traders',
    'Landlords',
    'Personal finances',
  ];

  @override
  State<WelcomeScreen> createState() => _WelcomeScreenState();
}

class _WelcomeScreenState extends State<WelcomeScreen> {
  String? _busy; // 'signin', 'company' or 'personal'
  String? _error;

  @override
  void initState() {
    super.initState();
    _error = widget.notice;
  }

  Future<void> _run(String what, Future<void> Function() work) async {
    if (_busy != null) return;
    setState(() {
      _busy = what;
      _error = null;
    });
    try {
      await work();
      await AppMode.refresh();
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = what == 'signin'
          ? friendlySignInMessage(e)
          : e is DemoException
              ? e.message
              : 'Could not reach Accnomos. Check your connection and try again.');
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  Future<void> _signIn() => _run('signin', () async {
        final custom = widget.signIn;
        if (custom != null) return custom();
        await AuthService().signIn();
      });

  Future<void> _demo(String kind) => _run(kind, () async {
        final custom = widget.startDemo;
        if (custom != null) return custom(kind);
        final settings = await AppSettings.load();
        await Demo.start(settings.runtimeUrl, kind);
      });

  Future<void> _open(String url) async {
    try {
      await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
    } catch (_) {
      // No browser: nothing else to do.
    }
  }

  @override
  Widget build(BuildContext context) {
    final busy = _busy != null;
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      body: ListView(
        padding: EdgeInsets.zero,
        children: [
          _Hero(),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 20, 16, 0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (_error != null) ...[
                  Container(
                    key: const Key('welcome-error'),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AccnomosColors.warnTint,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: const Color(0xFFF3C892)),
                    ),
                    child: Text(_error!,
                        style: const TextStyle(
                            color: AccnomosColors.warnText, height: 1.4)),
                  ),
                  const SizedBox(height: 14),
                ],
                FilledButton.icon(
                  key: const Key('welcome-sign-in'),
                  onPressed: busy ? null : _signIn,
                  icon: _busy == 'signin'
                      ? const _Spinner(light: true)
                      : const Icon(Icons.login),
                  label: const Text('Sign in with Microsoft'),
                  style: FilledButton.styleFrom(
                      minimumSize: const Size.fromHeight(50)),
                ),
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  key: const Key('welcome-demo-company'),
                  onPressed: busy ? null : () => _demo('company'),
                  icon: _busy == 'company'
                      ? const _Spinner()
                      : const Icon(Icons.storefront_outlined),
                  label: const Text('Try the company demo'),
                  style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(50)),
                ),
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  key: const Key('welcome-demo-personal'),
                  onPressed: busy ? null : () => _demo('personal'),
                  icon: _busy == 'personal'
                      ? const _Spinner()
                      : const Icon(Icons.home_outlined),
                  label: const Text('Try the personal demo'),
                  style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(50)),
                ),
                const SizedBox(height: 10),
                const Text(
                  'The demo uses fictional sample books and needs no sign-in. '
                  'HMRC contact is sandbox only.',
                  style: TextStyle(
                      color: AccnomosColors.muted, fontSize: 13, height: 1.4),
                ),
                const SizedBox(height: 26),
                Text('How it works',
                    style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: 10),
                for (final (i, step) in WelcomeScreen.steps.indexed) ...[
                  _StepCard(n: i + 1, title: step.$1, body: step.$2),
                  const SizedBox(height: 10),
                ],
                const SizedBox(height: 14),
                Text('One set of books, whoever you are',
                    style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final a in WelcomeScreen.audiences)
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 12, vertical: 8),
                        decoration: BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.circular(8),
                          border: const Border(
                            left: BorderSide(
                                color: AccnomosColors.brass, width: 3),
                            top: BorderSide(color: AccnomosColors.border),
                            right: BorderSide(color: AccnomosColors.border),
                            bottom: BorderSide(color: AccnomosColors.border),
                          ),
                        ),
                        child: Text(a,
                            style: const TextStyle(
                                fontWeight: FontWeight.w600,
                                color: AccnomosColors.ink)),
                      ),
                  ],
                ),
                const SizedBox(height: 22),
                Wrap(
                  alignment: WrapAlignment.center,
                  spacing: 4,
                  children: [
                    TextButton(
                        onPressed: () => _open('https://accnomos.com'),
                        child: const Text('accnomos.com')),
                    TextButton(
                        onPressed: () =>
                            _open('https://accnomos.com/how-it-works'),
                        child: const Text('How it works')),
                    TextButton(
                        onPressed: () => _open('https://accnomos.com/privacy'),
                        child: const Text('Privacy')),
                  ],
                ),
                SizedBox(height: 16 + MediaQuery.paddingOf(context).bottom),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Hero extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final top = MediaQuery.paddingOf(context).top;
    return Container(
      color: AccnomosColors.ledger,
      padding: EdgeInsets.fromLTRB(20, top + 18, 20, 26),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const BrandLockup(onDark: true, size: 34),
          const SizedBox(height: 26),
          Container(width: 36, height: 3, color: AccnomosColors.brass),
          const SizedBox(height: 12),
          Text(
            'Bookkeeping and Making Tax Digital for UK small businesses, sole '
            'traders, landlords and personal finances',
            style: TextStyle(
                color: AccnomosColors.markLight.withValues(alpha: 0.82),
                fontSize: 14,
                fontWeight: FontWeight.w600,
                height: 1.4),
          ),
          const SizedBox(height: 10),
          const Text(
            'Bookkeeping you only have to check',
            key: Key('welcome-headline'),
            style: TextStyle(
                color: AccnomosColors.markLight,
                fontSize: 31,
                fontWeight: FontWeight.w800,
                letterSpacing: -0.6,
                height: 1.12),
          ),
          const SizedBox(height: 12),
          Text(
            'The AI reads each document and proposes an entry. Nothing posts until you approve it.',
            style: TextStyle(
                color: AccnomosColors.markLight.withValues(alpha: 0.9),
                fontSize: 16,
                height: 1.45),
          ),
        ],
      ),
    );
  }
}

class _StepCard extends StatelessWidget {
  const _StepCard({required this.n, required this.title, required this.body});
  final int n;
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AccnomosColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Step $n',
              style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                  color: AccnomosColors.tealDark)),
          const SizedBox(height: 2),
          Text(title,
              style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: AccnomosColors.ink)),
          const SizedBox(height: 4),
          Text(body,
              style: const TextStyle(
                  color: AccnomosColors.muted, fontSize: 15, height: 1.45)),
        ],
      ),
    );
  }
}

class _Spinner extends StatelessWidget {
  const _Spinner({this.light = false});
  final bool light;

  @override
  Widget build(BuildContext context) => SizedBox(
        width: 18,
        height: 18,
        child: CircularProgressIndicator(
            strokeWidth: 2,
            color: light ? Colors.white : AccnomosColors.teal),
      );
}
