import 'dart:io';

import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';
import 'package:record/record.dart';

import '../models/ask_answer.dart';
import '../services/auth.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);

/// One live question and, once it arrives, its checked answer or an error.
class _Turn {
  _Turn(this.question, {this.spoken = false});
  final String question;

  /// True when the question came from a voice recording.
  final bool spoken;
  AskAnswer? answer;
  String? error;

  /// For a proposed action: the result once approved or rejected.
  String? actionResult;
  String? actionError;
  bool actionBusy = false;
}

/// Ask your books a question.
///
/// Signed in, typed questions go to `POST /books/ask`: numbers come from
/// code, words from the user's model. Hold the mic to ask with your voice
/// instead: the recording (WAV 16 kHz mono) goes to `POST /ask/voice` and
/// the transcript appears as your bubble with the answer below it. Signed
/// out, this screen shows a sample conversation.
class AskScreen extends StatefulWidget {
  const AskScreen({super.key});

  @override
  State<AskScreen> createState() => _AskScreenState();
}

class _AskScreenState extends State<AskScreen> {
  final TextEditingController _input = TextEditingController();
  final ScrollController _scroll = ScrollController();
  final AuthService _auth = AuthService();
  final AudioRecorder _mic = AudioRecorder();
  AppSettings? _settings;
  Account? _account;
  final List<_Turn> _turns = [];
  bool _busy = false;

  /// True between mic press and release; [_sendingVoice] while uploading.
  bool _recording = false;
  bool _sendingVoice = false;

  /// Last voice failure (e.g. local mode without transcription): shown
  /// above the thread with a prompt to type instead.
  String? _voiceError;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    _mic.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final settings = await AppSettings.load();
    Account? account;
    try {
      account = await _auth.account();
    } on MsalException {
      account = null;
    }
    if (!mounted) return;
    setState(() {
      _settings = settings;
      _account = account;
    });
  }

  Future<void> _send() async {
    final settings = _settings;
    final question = _input.text.trim();
    if (settings == null || _account == null || _busy || question.isEmpty) {
      return;
    }
    final history = <AskTurn>[
      for (final t in _turns)
        if (t.answer != null) ...[
          AskTurn(role: 'user', text: t.question),
          AskTurn(role: 'assistant', text: t.answer!.answerMd),
        ],
    ];
    final turn = _Turn(question);
    setState(() {
      _turns.add(turn);
      _busy = true;
      _input.clear();
    });
    _scrollToEnd();
    try {
      final client = await _client(settings);
      final answer = await client.ask(question, history: history);
      if (!mounted) return;
      setState(() => turn.answer = answer);
    } catch (e) {
      if (!mounted) return;
      setState(
          () => turn.error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
      _scrollToEnd();
    }
  }

  Future<RuntimeClient> _client(AppSettings settings) async {
    final token = await _auth.token();
    final user = _account?.username ?? settings.userEmail;
    return RuntimeClient(
      settings,
      books: BooksAuth(
        graphToken: token,
        accountKind: _auth.kind == AccountKind.work ? 'work' : 'personal',
        user: (user != null && user.isNotEmpty) ? user : null,
        businessName: settings.businessName,
      ),
    );
  }

  /// Approve or reject a proposed action. Nothing happens before this.
  Future<void> _decide(_Turn turn, {required bool approve}) async {
    final settings = _settings;
    final action = turn.answer?.proposedAction;
    if (settings == null || action == null || turn.actionBusy) return;
    setState(() {
      turn.actionBusy = true;
      turn.actionError = null;
    });
    try {
      final client = await _client(settings);
      final result = approve
          ? await client.approveAction(action)
          : await client.rejectAction(action);
      if (!mounted) return;
      setState(() => turn.actionResult = result);
    } catch (e) {
      if (!mounted) return;
      setState(() =>
          turn.actionError = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => turn.actionBusy = false);
    }
  }

  /// Mic pressed: start a WAV 16 kHz mono recording.
  Future<void> _startVoice() async {
    final settings = _settings;
    if (settings == null || _account == null) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text('Sign in to ask with your voice.')),
        );
      }
      return;
    }
    if (_busy || _sendingVoice || _recording) return;
    bool allowed = false;
    try {
      allowed = await _mic.hasPermission();
    } catch (_) {
      allowed = false;
    }
    if (!allowed) {
      if (!mounted) return;
      setState(() => _voiceError =
          'Microphone access was refused. Allow it in the phone '
          'settings, or type your question instead.');
      return;
    }
    final path =
        '${Directory.systemTemp.path}/accnomos_ask_${DateTime.now().millisecondsSinceEpoch}.wav';
    try {
      await _mic.start(
        const RecordConfig(
          encoder: AudioEncoder.wav,
          sampleRate: 16000,
          numChannels: 1,
        ),
        path: path,
      );
    } catch (_) {
      if (!mounted) return;
      setState(() => _voiceError =
          'Could not start recording. Type your question instead.');
      return;
    }
    if (!mounted) return;
    setState(() {
      _recording = true;
      _voiceError = null;
    });
  }

  /// Mic released: stop, upload to `POST /ask/voice`, and show the
  /// transcript as the user's bubble with the answer below it.
  Future<void> _stopVoiceAndSend() async {
    if (!_recording) return;
    String? path;
    try {
      path = await _mic.stop();
    } catch (_) {
      path = null;
    }
    if (!mounted) return;
    setState(() => _recording = false);
    if (path == null) {
      setState(() => _voiceError =
          'That recording was lost. Hold the mic and try again, '
          'or type your question instead.');
      return;
    }
    final file = File(path);
    List<int> bytes = const [];
    try {
      bytes = await file.readAsBytes();
    } catch (_) {
      bytes = const [];
    }
    try {
      await file.delete();
    } catch (_) {
      // Best effort: the OS clears the temp folder anyway.
    }
    if (bytes.isEmpty) {
      if (!mounted) return;
      setState(() => _voiceError =
          'Nothing was heard. Hold the mic a moment longer, '
          'or type your question instead.');
      return;
    }
    await _sendVoice(bytes);
  }

  /// Mic gesture cancelled: discard the recording.
  Future<void> _cancelVoice() async {
    if (!_recording) return;
    try {
      final path = await _mic.stop();
      if (path != null) {
        try {
          await File(path).delete();
        } catch (_) {
          // Best effort.
        }
      }
    } catch (_) {
      // Nothing to discard.
    }
    if (mounted) setState(() => _recording = false);
  }

  Future<void> _sendVoice(List<int> bytes) async {
    final settings = _settings;
    if (settings == null ||
        _account == null ||
        _busy ||
        _sendingVoice) {
      return;
    }
    setState(() => _sendingVoice = true);
    try {
      final client = await _client(settings);
      final result = await client.askVoice(bytes);
      if (!mounted) return;
      final transcript = result.transcript.trim();
      if (transcript.isEmpty && result.answer == null) {
        setState(() {
          _sendingVoice = false;
          _voiceError = 'Nothing was heard. Type your question instead.';
        });
        return;
      }
      final turn = _Turn(
        transcript.isEmpty ? '(no speech heard)' : transcript,
        spoken: true,
      );
      setState(() {
        _sendingVoice = false;
        _turns.add(turn);
        if (result.answer != null) {
          turn.answer = result.answer;
        } else {
          turn.error =
              'Heard you, but no answer came back. Your words are in '
              'the box below — send them as text instead.';
          _input.text = transcript;
        }
      });
    } catch (e) {
      // Local mode or no transcription (400/503): show the runtime's
      // message and fall back to typing.
      if (!mounted) return;
      setState(() {
        _sendingVoice = false;
        _voiceError = '${e.toString().replaceFirst('Exception: ', '')} '
            'Type your question instead.';
      });
    } finally {
      if (mounted) _scrollToEnd();
    }
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(
          _scroll.position.maxScrollExtent,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final live = _account != null;
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          'Ask',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
      ),
      body: Column(
        children: [
          Expanded(
            child: ListView(
              controller: _scroll,
              padding: const EdgeInsets.all(16),
              children: live ? _liveThread() : _sampleThread(),
            ),
          ),
          _inputRow(live),
        ],
      ),
    );
  }

  List<Widget> _sampleThread() {
    return [
      Align(
        alignment: Alignment.centerLeft,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(
            color: AccnomosColors.ink,
            borderRadius: BorderRadius.circular(12),
          ),
          child: const Text(
            'SAMPLE — FICTIONAL COMPANY',
            style: TextStyle(
              color: AccnomosColors.ground,
              fontSize: 11,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      ),
      const SizedBox(height: 12),
      _userBubble(),
      const SizedBox(height: 12),
      _answerCard(),
    ];
  }

  List<Widget> _liveThread() {
    final head = <Widget>[
      if (_voiceError != null) ...[
        _warnBox(_voiceError!),
        const SizedBox(height: 12),
      ],
    ];
    if (_turns.isEmpty) {
      return [
        ...head,
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: const Color(0xFFE3E1D8)),
          ),
          child: Text(
            'Ask about your current VAT quarter and the one before — '
            '“Why is my VAT different from last quarter?” or '
            '“Who did I spend most with?”. Numbers are calculated by code; '
            '${_settings?.aiModel ?? 'your AI'} only writes the words.',
            style: const TextStyle(color: AccnomosColors.muted, height: 1.4),
          ),
        ),
      ];
    }
    return [
      ...head,
      for (final t in _turns) ...[
        _questionBubble(t.question, spoken: t.spoken),
        const SizedBox(height: 12),
        if (t.answer?.proposedAction != null)
          _actionCard(t)
        else if (t.answer != null)
          _liveAnswer(t.answer!)
        else if (t.error != null)
          _warnBox('Couldn\'t get an answer. ${t.error}')
        else
          const Padding(
            padding: EdgeInsets.all(12),
            child: Text(
              'Reading your books…',
              style: TextStyle(color: AccnomosColors.muted),
            ),
          ),
        const SizedBox(height: 16),
      ],
    ];
  }

  Widget _questionBubble(String text, {bool spoken = false}) {
    return Align(
      alignment: Alignment.centerRight,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 320),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            if (spoken)
              const Padding(
                padding: EdgeInsets.only(bottom: 4),
                child: Text(
                  'Spoken',
                  style: TextStyle(
                    fontSize: 11,
                    color: AccnomosColors.muted,
                  ),
                ),
              ),
            Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              decoration: BoxDecoration(
                color: AccnomosColors.teal,
                borderRadius: BorderRadius.circular(16),
              ),
              child: Text(
                text,
                style:
                    const TextStyle(color: Colors.white, height: 1.4),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _warnBox(String text) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: _warnBg,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _warnBorder),
      ),
      child: Text(text, style: const TextStyle(color: _warnInk, height: 1.4)),
    );
  }

  /// `answer_md` as plain text: paragraphs, `-` bullets and `1.` lists.
  List<Widget> _markdown(String md) {
    final widgets = <Widget>[];
    final numbered = RegExp(r'^(\d+)[.)]\s+');
    final bullet = RegExp(r'^[-*•]\s+');
    for (final raw in md.split('\n')) {
      final line = raw.trim().replaceAll('**', '').replaceAll('`', '');
      if (line.isEmpty) continue;
      final n = numbered.firstMatch(line);
      if (n != null) {
        widgets.add(_numbered(n.group(1)!, line.substring(n.end)));
      } else if (bullet.hasMatch(line)) {
        widgets.add(_numbered('•', line.replaceFirst(bullet, ''), dot: false));
      } else {
        widgets.add(Padding(
          padding: EdgeInsets.only(top: widgets.isEmpty ? 0 : 8),
          child: Text(
            line.replaceFirst(RegExp(r'^#+\s*'), ''),
            style: const TextStyle(color: AccnomosColors.ink, height: 1.4),
          ),
        ));
      }
    }
    return widgets;
  }

  Widget _liveAnswer(AskAnswer a) {
    final muted = 'Numbers by code · words by ${a.model}'
        '${a.confidence == 'high' ? '' : ' · confidence ${a.confidence}'}';
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (a.fallbackReason != null) ...[
            _warnBox('${a.fallbackReason} These figures come straight '
                'from your ledger.'),
            const SizedBox(height: 10),
          ],
          ..._markdown(a.answerMd),
          if (a.keyNumbers.isNotEmpty) ...[
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final k in a.keyNumbers)
                  Tooltip(
                    message: 'From ${k.source}',
                    child: Chip(
                      backgroundColor: AccnomosColors.tealTint,
                      label: Text(
                        '${k.label}  ${k.value}',
                        style: const TextStyle(fontSize: 12),
                      ),
                    ),
                  ),
              ],
            ),
          ],
          if (a.citations.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final c in a.citations)
                  Chip(
                    label: Text(c, style: const TextStyle(fontSize: 12)),
                  ),
              ],
            ),
          ],
          const SizedBox(height: 8),
          Text(
            muted,
            style: const TextStyle(fontSize: 12, color: AccnomosColors.muted),
          ),
          if (a.suggestedActions.any((s) => s.kind != 'none')) ...[
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final s in a.suggestedActions)
                  if (s.kind != 'none')
                    ActionChip(
                      label: Text(s.label),
                      onPressed: () =>
                          ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          content: Text(s.kind == 'open_vat'
                              ? 'Open the VAT tab to see this.'
                              : 'Open the Review tab to see this.'),
                        ),
                      ),
                    ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  /// A proposed action: what will happen, then Approve / Reject.
  Widget _actionCard(_Turn t) {
    final a = t.answer!.proposedAction!;
    final expires = a.expiresAt;
    final expired = expires != null && DateTime.now().isAfter(expires);
    // The runtime escapes names in its markdown; this renderer shows text only.
    String plain(String md) => md
        .replaceAll(RegExp(r'^> ?', multiLine: true), '')
        .replaceAllMapped(RegExp(r'\\(.)'), (m) => m.group(1)!);
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AccnomosColors.teal, width: 2),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'PROPOSED · NEEDS YOUR OK',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: AccnomosColors.teal,
            ),
          ),
          const SizedBox(height: 8),
          ..._markdown(plain(a.summaryMd)),
          for (final w in a.warnings) ...[
            const SizedBox(height: 8),
            _warnBox(w),
          ],
          const SizedBox(height: 12),
          if (t.actionResult != null)
            Text(
              plain(t.actionResult!).replaceAll('**', ''),
              style: const TextStyle(
                color: AccnomosColors.teal,
                fontWeight: FontWeight.w700,
                height: 1.4,
              ),
            )
          else ...[
            Text(
              expired
                  ? 'This proposal has expired; ask again.'
                  : '${a.confirmText}?',
              style: const TextStyle(
                fontWeight: FontWeight.w700,
                color: AccnomosColors.ink,
              ),
            ),
            if (t.actionError != null) ...[
              const SizedBox(height: 8),
              _warnBox(t.actionError!),
            ],
            const SizedBox(height: 10),
            Row(
              children: [
                FilledButton(
                  style: FilledButton.styleFrom(
                    backgroundColor: AccnomosColors.teal,
                  ),
                  onPressed: t.actionBusy || expired
                      ? null
                      : () => _decide(t, approve: true),
                  child: Text(t.actionBusy ? 'Working…' : 'Approve'),
                ),
                const SizedBox(width: 8),
                TextButton(
                  onPressed:
                      t.actionBusy ? null : () => _decide(t, approve: false),
                  child: const Text('Reject'),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _userBubble() {
    return Align(
      alignment: Alignment.centerRight,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 320),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            const Text(
              'Spoken · Muse Voice',
              style: TextStyle(
                fontSize: 11,
                color: AccnomosColors.muted,
              ),
            ),
            const SizedBox(height: 4),
            Container(
              padding: const EdgeInsets.symmetric(
                horizontal: 14,
                vertical: 12,
              ),
              decoration: BoxDecoration(
                color: AccnomosColors.teal,
                borderRadius: BorderRadius.circular(16),
              ),
              child: const Text(
                'Why is my VAT higher than last quarter?',
                style: TextStyle(color: Colors.white, height: 1.4),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _numbered(String number, String text, {bool dot = true}) {
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 20,
            child: Text(
              dot ? '$number.' : number,
              style: const TextStyle(
                color: AccnomosColors.ink,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                color: AccnomosColors.ink,
                height: 1.4,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _answerCard() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Your Q3 bill is £2,140, up £620 on Q2. Two reasons:',
            style: TextStyle(
              color: AccnomosColors.ink,
              fontWeight: FontWeight.w700,
              height: 1.4,
            ),
          ),
          _numbered(
            '1',
            'Sales were £6,400 higher — the Hartley kitchen job (INV-0039, INV-0041).',
          ),
          _numbered(
            '2',
            'You reclaimed less: the Howdens invoice (£412 VAT) is still '
                'waiting for a VAT number, so it\'s not in Box 4 yet.',
          ),
          Container(
            width: double.infinity,
            margin: const EdgeInsets.only(top: 10),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: _warnBg,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: _warnBorder),
            ),
            child: const Text(
              'If Howdens sends the VAT invoice before 7 Nov, your bill '
                  'drops to about £1,728.',
              style: TextStyle(color: _warnInk, height: 1.4),
            ),
          ),
          const SizedBox(height: 10),
          const Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              Chip(
                label: Text(
                  '05 VAT returns/2026-Q3/return.json',
                  style: TextStyle(fontSize: 12),
                ),
              ),
              Chip(
                label: Text(
                  'Books.xlsx · VAT',
                  style: TextStyle(fontSize: 12),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
            'Numbers by code · explanation by Muse Spark · read aloud by your phone',
            style: TextStyle(
              fontSize: 12,
              color: AccnomosColors.muted,
            ),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              ActionChip(
                label: const Text('Chase Howdens for the invoice'),
                onPressed: () => setState(
                  () => _input.text = 'Chase Howdens for the invoice',
                ),
              ),
              ActionChip(
                label: const Text('Show Box 4 entries'),
                onPressed: () =>
                    setState(() => _input.text = 'Show Box 4 entries'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _inputRow(bool live) {
    final micActive = live && !_busy && !_sendingVoice;
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: Color(0xFFE3E1D8))),
      ),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (_recording)
              const Padding(
                padding: EdgeInsets.only(bottom: 8),
                child: Text(
                  'Listening… release to send',
                  style: TextStyle(
                    color: AccnomosColors.tealDark,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            Row(
              children: [
                GestureDetector(
                  onLongPressStart: (_) => _startVoice(),
                  onLongPressEnd: (_) => _stopVoiceAndSend(),
                  onLongPressCancel: _cancelVoice,
                  child: SizedBox(
                    width: 48,
                    height: 48,
                    child: FilledButton(
                      style: FilledButton.styleFrom(
                        backgroundColor: _recording
                            ? const Color(0xFFB3261E)
                            : AccnomosColors.teal,
                        padding: EdgeInsets.zero,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(24),
                        ),
                      ),
                      // Hold-to-talk is driven by the long-press above;
                      // a plain tap only explains the gesture.
                      onPressed: micActive
                          ? () => ScaffoldMessenger.of(context)
                              .showSnackBar(
                                const SnackBar(
                                  content: Text(
                                      'Hold the mic and speak, then release to send.'),
                                ),
                              )
                          : null,
                      child: _sendingVoice
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white,
                              ),
                            )
                          : const Icon(Icons.mic,
                              color: Colors.white),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: SizedBox(
                    height: 56,
                    child: TextField(
                      controller: _input,
                      enabled: !_busy && !_sendingVoice,
                      maxLength: 500,
                      textInputAction: TextInputAction.send,
                      onSubmitted: live ? (_) => _send() : null,
                      decoration: InputDecoration(
                        counterText: '',
                        hintText: live
                            ? 'Ask your books…'
                            : 'Sign in to ask your own books',
                        contentPadding:
                            const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 16,
                        ),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(28),
                        ),
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                SizedBox(
                  width: 48,
                  height: 48,
                  child: FilledButton(
                    style: FilledButton.styleFrom(
                      backgroundColor: AccnomosColors.teal,
                      padding: EdgeInsets.zero,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(24),
                      ),
                    ),
                    onPressed:
                        live && !_busy && !_sendingVoice
                            ? _send
                            : null,
                    child: live && _busy
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Icon(Icons.send,
                            color: Colors.white),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
