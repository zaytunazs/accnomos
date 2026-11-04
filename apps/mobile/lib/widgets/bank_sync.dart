import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../services/runtime_client.dart';
import '../theme.dart';

/// Bank › Automatic bank sync, as on the web's Bank page: each connected bank
/// with its last sync and a "Sync now" button; with none connected, how to set
/// it up (connecting a bank happens on the web, where the bank's own sign-in
/// opens). Hidden where feeds are not offered (books outside the UK).
class BankSyncCard extends StatefulWidget {
  const BankSyncCard({
    super.key,
    required this.clientFor,
    required this.onSynced,
    this.openUrl,
  });

  final Future<RuntimeClient> Function() clientFor;
  final VoidCallback onSynced;

  /// Opens the web Bank page; tests pass a fake.
  final Future<void> Function(Uri url)? openUrl;

  static final setupUrl = Uri.parse('https://accnomos.com/bank');

  @override
  State<BankSyncCard> createState() => _BankSyncCardState();
}

class _BankSyncCardState extends State<BankSyncCard> {
  Map<String, dynamic>? _status;
  bool _syncing = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final s = await (await widget.clientFor()).bankFeeds();
      if (mounted) setState(() => _status = s);
    } catch (_) {
      // No card when the status cannot be read: statements still import.
    }
  }

  Future<void> _sync() async {
    setState(() => _syncing = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final r = await (await widget.clientFor()).syncBankFeeds();
      final n = (r['new_lines'] as num?)?.toInt() ?? 0;
      messenger.showSnackBar(SnackBar(
          content: Text(n == 0
              ? 'Bank synced: no new lines.'
              : 'Bank synced: $n new ${n == 1 ? 'line' : 'lines'}.')));
      widget.onSynced();
      await _load();
    } catch (e) {
      messenger.showSnackBar(SnackBar(
          content: Text(e.toString().replaceFirst('Exception: ', ''))));
    } finally {
      if (mounted) setState(() => _syncing = false);
    }
  }

  Future<void> _setup() async {
    final open = widget.openUrl ??
        (Uri u) async {
          await launchUrl(u, mode: LaunchMode.externalApplication);
        };
    await open(BankSyncCard.setupUrl);
  }

  static String _day(Object? iso) {
    final d = DateTime.tryParse(iso?.toString() ?? '');
    if (d == null) return 'not yet';
    const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    final l = d.toLocal();
    return '${l.day} ${m[l.month - 1]} ${l.year}';
  }

  @override
  Widget build(BuildContext context) {
    final s = _status;
    if (s == null || s['available'] != true) return const SizedBox.shrink();
    final conns = [
      if (s['connections'] is List)
        for (final c in s['connections'] as List)
          if (c is Map) Map<String, dynamic>.from(c),
    ];
    final sandbox = s['sandbox'] == true;
    // A demo session: TrueLayer's test bank only, labelled as such (docs/BANK_FEED_SANDBOX_DEMO.md).
    final demo = s['demo'] == true;
    final label = (s['label'] ?? '').toString();
    return Container(
      key: const Key('bank-sync'),
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AccnomosColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            const Icon(Icons.sync, color: AccnomosColors.teal),
            const SizedBox(width: 8),
            const Expanded(
              child: Text('Automatic bank sync',
                  style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
            ),
            if (sandbox && !(demo && label.isNotEmpty))
              const Text('Bank sandbox',
                  style: TextStyle(color: AccnomosColors.muted, fontSize: 12)),
          ]),
          if (demo && label.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(label,
                  key: const Key('bank-sync-demo-label'),
                  style: const TextStyle(
                      color: AccnomosColors.muted,
                      fontSize: 12,
                      fontWeight: FontWeight.w700)),
            ),
          const SizedBox(height: 6),
          if (conns.isEmpty) ...[
            Text(
              demo
                  ? 'In the demo, the bank feed connects TrueLayer’s test bank '
                      'on the web demo’s Bank page. The web demo is its own '
                      'demo session, so a bank connected there shows there; a '
                      'bank connected in this demo session shows here with '
                      'Sync now.'
                  : 'Connect your bank once and new lines come in by themselves, '
                      'read-only. You set it up on the web, where your bank’s own '
                      'sign-in opens; then sync here any time.',
              style: const TextStyle(color: AccnomosColors.ink, height: 1.4),
            ),
            const SizedBox(height: 10),
            OutlinedButton.icon(
              key: const Key('bank-sync-setup'),
              onPressed: _setup,
              icon: const Icon(Icons.open_in_new),
              label: const Text('Set up automatic sync'),
            ),
          ] else ...[
            for (final c in conns)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text(
                  '${c['bank'] ?? 'Bank'} · last synced ${_day(c['last_synced_at'])}'
                  '${(c['message'] ?? '').toString().isNotEmpty ? '\n${c['message']}' : ''}',
                  style: const TextStyle(color: AccnomosColors.ink, height: 1.4),
                ),
              ),
            const SizedBox(height: 4),
            FilledButton.icon(
              key: const Key('bank-sync-now'),
              style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size.fromHeight(48)),
              onPressed: _syncing ? null : _sync,
              icon: _syncing
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: Colors.white))
                  : const Icon(Icons.sync),
              label: Text(_syncing ? 'Syncing…' : 'Sync now'),
            ),
          ],
        ],
      ),
    );
  }
}
