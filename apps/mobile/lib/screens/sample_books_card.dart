import 'dart:async';

import 'package:flutter/material.dart';

import '../models/sample_books.dart';
import '../services/books.dart' show friendly;
import '../services/runtime_client.dart';
import '../theme.dart';
import 'home_cards.dart' show HomeCard;

/// Poll the status this often while loading (the web uses 3 s too).
const sampleBooksPollInterval = Duration(seconds: 3);

/// Hand the runtime a fresh Graph token this often (a token lasts about an hour).
const sampleBooksContinueInterval = Duration(minutes: 4);

/// Home › "Load sample books", like the web's `SampleBooks` card. Shown only
/// when signed in and the folder is empty, or a load is running, waiting for
/// a token or stopped. Polls `GET /books/sample` while the screen is
/// visible; every 4 minutes, and whenever the runtime says `needs_token`, it
/// posts `/books/sample/continue` so the background job gets a fresh token.
/// When the load finishes [onLoaded] runs (Home refreshes) and the card
/// becomes the "SAMPLE — FICTIONAL COMPANY" banner.
class SampleBooksCard extends StatefulWidget {
  const SampleBooksCard({
    super.key,
    required this.clientFor,
    this.onLoaded,
    this.pollInterval = sampleBooksPollInterval,
    this.continueInterval = sampleBooksContinueInterval,
  });

  /// A client with the signed-in books credentials (fresh token each call).
  final Future<RuntimeClient> Function() clientFor;

  /// Called once when a load this card watched finishes.
  final VoidCallback? onLoaded;

  final Duration pollInterval;
  final Duration continueInterval;

  @override
  State<SampleBooksCard> createState() => _SampleBooksCardState();
}

class _SampleBooksCardState extends State<SampleBooksCard>
    with WidgetsBindingObserver {
  SampleStatus? _status;
  String? _note;
  bool _busy = false;
  bool _polling = false;
  bool _sawRunning = false;
  bool _notified = false;
  bool _foreground = true;
  int _ticksSincePost = 0;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _fetch();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _timer?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
  }

  Future<void> _fetch() async {
    try {
      final client = await widget.clientFor();
      final status = await client.sampleBooksStatus();
      if (!mounted) return;
      _apply(status);
    } catch (_) {
      // The runtime is unreachable: Home says so elsewhere. Show nothing
      // until a poll gets through.
      if (mounted && _status == null) setState(() => _status = null);
    }
  }

  void _apply(SampleStatus status) {
    setState(() => _status = status);
    if (status.running) {
      _sawRunning = true;
      _timer ??= Timer.periodic(widget.pollInterval, (_) => _tick());
    } else {
      _timer?.cancel();
      _timer = null;
      if (status.state == 'done' && _sawRunning && !_notified) {
        _notified = true;
        widget.onLoaded?.call();
      }
    }
  }

  /// One poll. Skipped while the Home tab is hidden (TickerMode is off for
  /// an IndexedStack tab that is not showing) or the app is in the background.
  Future<void> _tick() async {
    if (_polling || !mounted || !_foreground || !TickerMode.valuesOf(context).enabled) {
      return;
    }
    _polling = true;
    try {
      final client = await widget.clientFor();
      var status = await client.sampleBooksStatus();
      if (!mounted) return;
      _ticksSincePost++;
      final every = widget.continueInterval.inMilliseconds ~/
          widget.pollInterval.inMilliseconds;
      if (status.state == 'needs_token' || _ticksSincePost >= every) {
        _ticksSincePost = 0;
        try {
          status = await client.loadSampleBooks(carryOn: true);
        } on SampleNote {
          // Rate limited or similar: the next poll tries again.
        }
      }
      if (!mounted) return;
      _apply(status);
    } catch (_) {
      // One missed poll: the next one tries again.
    } finally {
      _polling = false;
    }
  }

  Future<void> _start() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _note = null;
    });
    try {
      final client = await widget.clientFor();
      final status = await client.loadSampleBooks();
      if (!mounted) return;
      _ticksSincePost = 0;
      _apply(status);
    } on SampleNote catch (n) {
      if (mounted) setState(() => _note = n.message);
    } catch (e) {
      if (mounted) setState(() => _note = friendly(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final status = _status;
    if (status == null) return const SizedBox.shrink();
    if (status.state == 'done') return SampleBanner(business: status.business);
    if (status.state == 'none' && status.empty != true) {
      return const SizedBox.shrink(); // the folder has books: never mix them
    }
    final failed = status.state == 'failed';
    final running = status.running;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AccnomosColors.tealTint,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AccnomosColors.teal),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(
            header: true,
            child: Text(
              running ? 'Loading sample books…' : 'Try it with sample books',
              style: const TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: 15,
                  color: AccnomosColors.tealDark),
            ),
          ),
          if (!running && !failed) ...[
            const SizedBox(height: 4),
            const Text(
              'Loads six months of a fictional joinery business (labelled '
              'SAMPLE) into your Accnomos folder. You can delete it any time '
              'by deleting the folder in OneDrive.',
              style: TextStyle(
                  color: AccnomosColors.ink, fontSize: 13, height: 1.4),
            ),
          ],
          if (running || failed) SampleProgress(status: status),
          if (failed && status.error != null) ...[
            const SizedBox(height: 8),
            Text(status.error!,
                style: const TextStyle(
                    color: AccnomosColors.ink,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    height: 1.4)),
          ],
          if (_note != null) ...[
            const SizedBox(height: 8),
            Text(_note!,
                key: const Key('sample-note'),
                style: const TextStyle(
                    color: Color(0xFF8A3F06),
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    height: 1.4)),
          ],
          if (!running) ...[
            const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                style: FilledButton.styleFrom(
                    backgroundColor: AccnomosColors.teal,
                    minimumSize: const Size.fromHeight(46),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12))),
                onPressed: _busy ? null : _start,
                child: Text(
                  failed
                      ? 'Carry on loading sample books'
                      : _busy
                          ? 'Starting…'
                          : 'Load sample books',
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// The bar plus "step N of M" and the step being done.
class SampleProgress extends StatelessWidget {
  const SampleProgress({super.key, required this.status});
  final SampleStatus status;

  @override
  Widget build(BuildContext context) {
    final total = status.total;
    final done = status.done.clamp(0, total == 0 ? 0 : total);
    final fraction = total == 0 ? 0.0 : done / total;
    // "step N of M": N is the step being done (done + 1), capped at M.
    final current = total == 0 ? 0 : (done + 1 > total ? total : done + 1);
    final now = status.state == 'needs_token'
        ? 'Waiting for your sign-in to renew…'
        : (status.step ?? 'Starting…');
    final spoken = total == 0
        ? 'Loading sample books, starting'
        : 'Loading sample books, step $current of $total'
            '${status.step != null ? ': ${status.step}' : ''}';
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Semantics(
        label: spoken,
        liveRegion: true,
        excludeSemantics: true,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(6),
              child: LinearProgressIndicator(
                value: fraction,
                minHeight: 10,
                backgroundColor: Colors.white,
                color: AccnomosColors.teal,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              total == 0 ? 'Starting…' : 'Step $current of $total',
              key: const Key('sample-step-count'),
              style: const TextStyle(
                  color: AccnomosColors.muted,
                  fontSize: 12,
                  fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 2),
            Text(now,
                key: const Key('sample-step-name'),
                style: const TextStyle(
                    color: AccnomosColors.ink,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    height: 1.35)),
            if (status.state == 'running') ...[
              const SizedBox(height: 6),
              const Text(
                'Keep Home open; it takes a few minutes.',
                style: TextStyle(color: AccnomosColors.muted, fontSize: 12),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Home, once sample books are in the folder: say so plainly, like the web.
class SampleBanner extends StatelessWidget {
  const SampleBanner({super.key, this.business});
  final String? business;

  @override
  Widget build(BuildContext context) {
    return HomeCard(
      label: 'Sample books',
      sampled: true,
      child: Text(
        'These are sample books for ${business ?? 'a made-up company'}, '
        'loaded to try Accnomos. Every document in them is fictional. To '
        'start on your own books, delete the Accnomos folder in OneDrive.',
        style: const TextStyle(
            color: AccnomosColors.ink, fontSize: 13, height: 1.4),
      ),
    );
  }
}
