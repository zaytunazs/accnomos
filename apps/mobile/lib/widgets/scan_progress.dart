import 'dart:async';

import 'package:flutter/material.dart';

import '../models/scan_job.dart';
import '../theme.dart';

/// One background scan on the phone, as the web's ScanProgress
/// (`apps/web/src/components/review/ScanProgress.tsx`): a progress bar for
/// the job and one per file, the AI's guess of each file's type with how
/// sure it is, a choice of type and Confirm. Nothing is read in full, filed
/// or posted until the user confirms. It asks the runtime how the job is
/// doing every [pollEvery] while something is being read (slower while it
/// only waits for the user), and stops once the job is done; the reading
/// itself carries on on the server if the app is closed.
class ScanJobCard extends StatefulWidget {
  const ScanJobCard({
    super.key,
    required this.job,
    required this.load,
    required this.confirm,
    this.onFiled,
    this.onDismiss,
    this.pollEvery = const Duration(milliseconds: 1500),
    this.waitEvery = const Duration(seconds: 10),
  });

  final ScanJob job;
  final Future<ScanJob> Function(String id) load;
  final Future<ScanJob> Function(String id, Map<String, String> kinds)
      confirm;

  /// Called with how many new cards reached Review or Needs a look.
  final void Function(int cards)? onFiled;
  final VoidCallback? onDismiss;
  final Duration pollEvery;
  final Duration waitEvery;

  @override
  State<ScanJobCard> createState() => _ScanJobCardState();
}

class _ScanJobCardState extends State<ScanJobCard> {
  late ScanJob _job = widget.job;
  final Map<String, String> _choice = {};
  Timer? _timer;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _schedule();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _schedule() {
    _timer?.cancel();
    if (_job.done) return;
    _timer = Timer(_job.working ? widget.pollEvery : widget.waitEvery, _poll);
  }

  void _take(ScanJob next) {
    final more = next.cards - _job.cards;
    setState(() => _job = next);
    if (more > 0) widget.onFiled?.call(more);
    _schedule();
  }

  Future<void> _poll() async {
    try {
      final next = await widget.load(_job.id);
      if (!mounted) return;
      _take(next);
    } catch (_) {
      if (mounted) _schedule(); // offline for a moment: ask again
    }
  }

  String _kindOf(ScanFile f) => _choice[f.name] ?? f.guess?.kind ?? 'other';

  Future<void> _confirm(List<ScanFile> files) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final next = await widget
          .confirm(_job.id, {for (final f in files) f.name: _kindOf(f)});
      if (!mounted) return;
      _take(next);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final waiting = _job.toConfirm;
    return Card(
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Semantics(
              liveRegion: true,
              child: Text(_job.headline,
                  style: const TextStyle(fontWeight: FontWeight.w800)),
            ),
            const SizedBox(height: 4),
            const Text('It carries on if you leave this screen.',
                style: TextStyle(color: AccnomosColors.muted, fontSize: 12)),
            const SizedBox(height: 8),
            LinearProgressIndicator(
              value: _job.progress,
              semanticsLabel: 'Overall progress',
              semanticsValue: '${(_job.progress * 100).round()}%',
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(_error!,
                    style: const TextStyle(color: Color(0xFF8A4B0F))),
              ),
            for (final f in _job.files) _row(f),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                if (waiting.length > 1)
                  FilledButton(
                    onPressed: _busy ? null : () => _confirm(waiting),
                    child: Text('Confirm all ${waiting.length}'),
                  ),
                if (_job.done && widget.onDismiss != null)
                  TextButton(
                      onPressed: widget.onDismiss,
                      child: const Text('Dismiss')),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _row(ScanFile f) {
    final guess = f.guess;
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                  child: Text(f.name,
                      style: const TextStyle(fontWeight: FontWeight.w700))),
              Text(f.stageLabel,
                  style: const TextStyle(
                      color: AccnomosColors.teal, fontSize: 12)),
            ],
          ),
          const SizedBox(height: 4),
          LinearProgressIndicator(
            value: f.progress,
            semanticsLabel: '${f.name}: ${f.stageLabel}',
            semanticsValue: '${(f.progress * 100).round()}%',
          ),
          if (f.waitingForType && guess != null) ...[
            const SizedBox(height: 6),
            Text(
              'Looks like a ${guess.label.toLowerCase()} '
              '(${guess.percent}% sure${guess.byCode ? ', guessed by code' : ''}). '
              '${guess.reason}',
            ),
            Row(
              children: [
                Expanded(
                  child: DropdownButton<String>(
                    isExpanded: true,
                    value: _kindOf(f),
                    items: [
                      for (final e in scanKindLabels.entries)
                        DropdownMenuItem(value: e.key, child: Text(e.value)),
                    ],
                    onChanged: _busy
                        ? null
                        : (v) => setState(() => _choice[f.name] = v ?? 'other'),
                  ),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: _busy ? null : () => _confirm([f]),
                  child: const Text('Confirm'),
                ),
              ],
            ),
          ],
          if (f.message != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(f.message!,
                  style: const TextStyle(
                      color: AccnomosColors.muted, height: 1.3)),
            ),
        ],
      ),
    );
  }
}
