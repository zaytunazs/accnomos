import 'dart:io';

import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';
import 'package:record/record.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/ask_answer.dart';
import '../models/ask_suggestions.dart';
import '../models/day_plan.dart';
import '../services/auth.dart';
import '../services/books.dart' show gbp;
import '../services/graph.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);

/// Why the mic is off, or null when voice can be used. [health] is the
/// reader's `GET /health` (null when it did not answer).
String? voiceOffReason(String aiMode, Map<String, dynamic>? health) {
  if (health != null && health['voice'] == false) {
    return 'Voice isn\'t available on your reader service (ffmpeg is missing)';
  }
  final stt = health?['stt'];
  final serverStt =
      stt is List && stt.any((p) => p is Map && p['configured'] == true);
  if (aiMode != 'key' && !serverStt) {
    return 'Voice needs a Meta API key — switch to key mode in Settings, '
        'or set up speech-to-text on your reader service';
  }
  return null;
}

/// A spoken question's "Spoken" label, with the service that heard it.
String spokenLabel(String? heardBy) =>
    heardBy == null ? 'Spoken' : 'Spoken · Transcribed by $heardBy';

/// The small label above a spoken question's bubble.
class SpokenTag extends StatelessWidget {
  const SpokenTag({super.key, this.heardBy});
  final String? heardBy;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 4),
        child: Text(
          spokenLabel(heardBy),
          style: const TextStyle(fontSize: 11, color: AccnomosColors.muted),
        ),
      );
}

/// One live question and, once it arrives, its checked answer or an error.
class _Turn {
  _Turn(this.question, {this.spoken = false, this.heardBy});
  final String question;

  /// True when the question came from a voice recording.
  final bool spoken;

  /// The speech-to-text service that heard it, shown as "Transcribed by …".
  final String? heardBy;
  AskAnswer? answer;
  String? error;

  /// Seconds the answer took, timed around the ask call.
  double? elapsedS;

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
  final FocusNode _focus = FocusNode();
  final AuthService _auth = AuthService();
  final GraphService _graph = GraphService();
  final AudioRecorder _mic = AudioRecorder();
  AppSettings? _settings;
  Account? _account;
  final List<_Turn> _turns = [];
  bool _busy = false;

  /// Starters for an empty thread, built from the dashboard payload in code.
  List<String>? _suggestions;

  /// Why the mic is disabled, if it is (key mode and reader voice needed).
  String? _voiceOff;

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
    _focus.dispose();
    _graph.close();
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
    if (account == null) return;
    // Voice needs a reader whose `/health` reports voice (ffmpeg), and a
    // speech-to-text service: the user's own Meta key (key mode) or one the
    // server has set up (`stt` in /health). Otherwise the mic stays off.
    try {
      final client = await _client(settings);
      final health = await client.health();
      if (!mounted) return;
      setState(() => _voiceOff = voiceOffReason(settings.aiMode, health));
    } catch (_) {
      // Offline: the mic keeps its key-mode gating.
      if (mounted) {
        setState(() => _voiceOff = voiceOffReason(settings.aiMode, null));
      }
    }
    await _refreshSuggestions();
  }

  /// Starters for an empty thread from the dashboard payload (code, not a
  /// model), like the web's `suggestedQuestions`. Falls back when the
  /// dashboard cannot be read.
  Future<void> _refreshSuggestions() async {
    final settings = _settings;
    if (settings == null || _account == null || _turns.isNotEmpty) return;
    try {
      final client = await _client(settings);
      final dashboard = await client.dashboard(today: _today());
      if (!mounted) return;
      setState(() => _suggestions = suggestedAskQuestions(dashboard));
    } catch (_) {
      if (!mounted) return;
      setState(() => _suggestions = askFallbackQuestions);
    }
  }

  static String _today() {
    final d = DateTime.now();
    String two(int n) => n.toString().padLeft(2, '0');
    return '${d.year}-${two(d.month)}-${two(d.day)}';
  }

  Future<void> _send() => _askQuestion(_input.text.trim());

  /// Ask [raw] as the next turn. Times the call for the answer footer and
  /// keeps only the last six turns in memory for this session.
  Future<void> _askQuestion(String raw) async {
    final settings = _settings;
    final question = raw.trim();
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
    final started = DateTime.now();
    setState(() {
      _turns.add(turn);
      if (_turns.length > 6) {
        _turns.removeRange(0, _turns.length - 6);
      }
      _busy = true;
      _input.clear();
      _suggestions = null;
    });
    _scrollToEnd();
    try {
      final client = await _client(settings);
      final answer = await client.ask(question, history: history);
      if (!mounted) return;
      setState(() {
        turn.answer = answer;
        turn.elapsedS =
            DateTime.now().difference(started).inMilliseconds / 1000;
      });
    } catch (e) {
      if (!mounted) return;
      setState(
          () => turn.error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
      _scrollToEnd();
    }
  }

  /// Start over: forget this session's turns and offer starters again.
  void _newConversation() {
    setState(() => _turns.clear());
    _refreshSuggestions();
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

  /// Mic pressed: start a WAV 16 kHz mono recording. Refuses with the
  /// reason when voice is disabled (key mode and reader voice needed).
  Future<void> _startVoice() async {
    if (_voiceOff != null) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(_voiceOff!)),
        );
      }
      return;
    }
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
        heardBy: result.transcribedBy,
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
        if (_suggestions != null) ...[
          const SizedBox(height: 12),
          const Text(
            'Try one of these',
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w700,
              color: AccnomosColors.muted,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final s in _suggestions!)
                ActionChip(
                  label: Text(s),
                  onPressed: _busy ? null : () => _askQuestion(s),
                ),
            ],
          ),
        ],
      ];
    }
    return [
      ...head,
      Align(
        alignment: Alignment.centerRight,
        child: TextButton(
          onPressed: _busy ? null : _newConversation,
          child: const Text('New conversation'),
        ),
      ),
      for (final t in _turns) ...[
        _questionBubble(
          t.question,
          spoken: t.spoken,
          heardBy: t.heardBy,
          onEdit: t.spoken && !_busy
              ? () {
                  _input.text = t.question;
                  _focus.requestFocus();
                }
              : null,
        ),
        const SizedBox(height: 12),
        if (t.answer?.proposedAction != null)
          _actionCard(t)
        else if (t.answer?.clarification != null)
          _clarifyCard(t)
        else if (t.answer != null)
          _liveAnswer(t.answer!, elapsedS: t.elapsedS)
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

  /// A sent question. A spoken one is a button when [onEdit] is set:
  /// tapping puts the transcript back in the box to edit, like the web.
  Widget _questionBubble(String text,
      {bool spoken = false, String? heardBy, VoidCallback? onEdit}) {
    return Align(
      alignment: Alignment.centerRight,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 320),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            if (spoken) SpokenTag(heardBy: heardBy),
            if (spoken && onEdit != null)
              GestureDetector(
                onTap: onEdit,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 14, vertical: 12),
                  decoration: BoxDecoration(
                    color: AccnomosColors.teal,
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Text(
                    text,
                    style: const TextStyle(
                        color: Colors.white, height: 1.4),
                  ),
                ),
              )
            else
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
            if (spoken && onEdit != null)
              const Padding(
                padding: EdgeInsets.only(top: 4),
                child: Text(
                  'Tap to edit before sending',
                  style: TextStyle(
                    fontSize: 11,
                    color: AccnomosColors.muted,
                  ),
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

  /// One checked answer: words, key numbers, cited files and next steps.
  Widget _liveAnswer(AskAnswer a, {double? elapsedS}) {
    final elapsed = elapsedS != null && elapsedS.isFinite
        ? ' · ${elapsedS < 10 ? elapsedS.toStringAsFixed(1) : elapsedS.round()} s'
        : '';
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
            Table(
              columnWidths: const {
                0: FlexColumnWidth(),
                1: IntrinsicColumnWidth(),
              },
              children: [
                for (final k in a.keyNumbers)
                  TableRow(
                    children: [
                      Padding(
                        padding:
                            const EdgeInsets.only(right: 12, top: 4, bottom: 4),
                        child: Tooltip(
                          message: 'From ${k.source}',
                          child: Text(
                            k.label,
                            style: const TextStyle(
                              fontSize: 13,
                              color: AccnomosColors.muted,
                            ),
                          ),
                        ),
                      ),
                      Padding(
                        padding:
                            const EdgeInsets.only(top: 4, bottom: 4),
                        child: Text(
                          k.value,
                          textAlign: TextAlign.right,
                          style: const TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w800,
                            color: AccnomosColors.tealDark,
                          ),
                        ),
                      ),
                    ],
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
                  _CitationChip(
                    citation: c,
                    sheet: c == 'Books.xlsx' ? workbookSheet(a) : null,
                  ),
              ],
            ),
          ],
          const SizedBox(height: 8),
          Text(
            'numbers by code · explanation by ${a.model}$elapsed',
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
                      onPressed: s.kind == 'plan_day' &&
                              (s.arg ?? '').isNotEmpty
                          ? () => _openPlan(s.arg!)
                          : () =>
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

  /// A `plan_day` suggested action: the day-plan sheet for [date]
  /// (`YYYY-MM-DD`). Asks for the calendar scope only when opened.
  Future<void> _openPlan(String date) async {
    final settings = _settings;
    if (settings == null || _account == null) return;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.85,
        minChildSize: 0.5,
        maxChildSize: 0.95,
        builder: (_, controller) => _PlanSheet(
          date: date,
          settings: settings,
          auth: _auth,
          account: _account,
          scroll: controller,
        ),
      ),
    );
  }

  /// "a.m."-free UK clock, e.g. "14:30", whatever the device time zone.
  static String _clock(String iso) {
    final d = DateTime.tryParse(iso)?.toLocal();
    if (d == null) return iso;
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(d.hour)}:${two(d.minute)}';
  }

  /// "29 October" from "2026-10-29", without going through a time zone.
  static String _dayLabel(String iso) {
    const months = [
      'January', 'February', 'March', 'April', 'May', 'June',
      'July', 'August', 'September', 'October', 'November', 'December',
    ];
    final parts = iso.split('-');
    if (parts.length < 3) return iso;
    final m = int.tryParse(parts[1]) ?? 0;
    final d = int.tryParse(parts[2]) ?? 0;
    if (m < 1 || m > 12 || d < 1) return iso;
    return '$d ${months[m - 1]}';
  }

  /// "27 October 2026" from "2026-10-27", without a time zone.
  static String _longDate(String iso) {
    final text = iso.trim();
    if (text.length < 10) return text;
    final day = _dayLabel(text.substring(0, 10));
    if (day == text.substring(0, 10)) return text;
    return '$day ${text.substring(0, 4)}';
  }

  static const _actionTitles = {
    'create_invoice': 'Invoice',
    'chase_invoice': 'Payment reminder',
    'log_timesheet': 'Timesheet',
    'log_mileage': 'Mileage',
    'pay_overtime': 'Overtime pay',
  };

  /// One label/value row, like the web's action details.
  Widget _detailRow(String label, Widget value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 72,
            child: Text(
              label,
              style: const TextStyle(
                fontSize: 14,
                color: AccnomosColors.muted,
              ),
            ),
          ),
          Expanded(
            child: DefaultTextStyle(
              style: const TextStyle(
                fontSize: 14,
                height: 1.5,
                color: AccnomosColors.ink,
              ),
              child: value,
            ),
          ),
        ],
      ),
    );
  }

  /// Exactly what the proposed action will do: recipient, amount, lines and
  /// date from the priced preview — the same rows as the web card.
  List<Widget> _actionDetails(ProposedAction a) {
    final p = a.raw['preview'] is Map
        ? Map<String, dynamic>.from(a.raw['preview'] as Map)
        : <String, dynamic>{};
    num pence(Object? v) => v is num ? v : 0;
    String str(Object? v) => (v ?? '').toString();
    List<Map<String, dynamic>> maps(Object? v) => [
          if (v is List)
            for (final i in v)
              if (i is Map) Map<String, dynamic>.from(i),
        ];
    if (a.kind == 'create_invoice') {
      final customer = p['customer'] is Map
          ? Map<String, dynamic>.from(p['customer'] as Map)
          : <String, dynamic>{};
      final lines = maps(p['lines']);
      final vat = maps(p['vat_summary']);
      final send = p['send'] == true;
      return [
        _detailRow(
          'To',
          Text.rich(
            TextSpan(
              children: [
                TextSpan(
                  text: str(customer['name']),
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                TextSpan(
                  text: send && str(p['send_to']).isNotEmpty
                      ? ' · emailed to ${p['send_to']}'
                      : ' · saved as a draft, not sent',
                  style:
                      const TextStyle(color: AccnomosColors.muted),
                ),
              ],
            ),
          ),
        ),
        _detailRow(
          'For',
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final l in lines)
                Padding(
                  padding: const EdgeInsets.only(bottom: 2),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          '${str(l['description'])}'
                          '${str(l['quantity']) != '1' ? ' × ${l['quantity']}' : ''}',
                        ),
                      ),
                      Text(gbp(pence(l['net_pence']))),
                    ],
                  ),
                ),
            ],
          ),
        ),
        _detailRow(
          'VAT',
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final v in vat)
                Row(
                  children: [
                    Expanded(child: Text(_vatLine(v))),
                    Text(gbp(pence(v['vat_pence']))),
                  ],
                ),
            ],
          ),
        ),
        _detailRow(
          'Total',
          Row(
            children: [
              Expanded(
                child: Text(
                  'Due ${_longDate(str(p['due_date']))}',
                  style:
                      const TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
              Text(
                gbp(pence(p['total_pence'])),
                style: const TextStyle(
                  fontWeight: FontWeight.w800,
                  color: AccnomosColors.tealDark,
                ),
              ),
            ],
          ),
        ),
      ];
    }
    if (a.kind == 'chase_invoice') {
      final overdue = pence(p['days_overdue']).toInt();
      return [
        _detailRow(
          'Invoice',
          Text.rich(
            TextSpan(
              children: [
                TextSpan(
                  text: str(p['invoice']),
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                TextSpan(text: ' · ${str(p['customer'])} · '),
                TextSpan(text: gbp(pence(p['total_pence']))),
                TextSpan(
                  text: overdue > 0
                      ? ' · $overdue days overdue'
                      : ' · due ${_longDate(str(p['due_date']))}',
                  style:
                      const TextStyle(color: AccnomosColors.muted),
                ),
              ],
            ),
          ),
        ),
        _detailRow('To', Text(str(p['to']))),
        _detailRow('Subject', Text(str(p['subject']))),
        _detailRow(
          'Message',
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AccnomosColors.ground,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(str(p['body'])),
          ),
        ),
      ];
    }
    if (a.kind == 'pay_overtime') {
      return [
        _detailRow('Who', Text(str(p['staff_name']))),
        if (str(p['job_name']).isNotEmpty)
          _detailRow('Job', Text(str(p['job_name']))),
        _detailRow('Week',
            Text('${_longDate(str(p['week_start']))} – ${_longDate(str(p['week_end']))}')),
        _detailRow(
          'Hours',
          Text(
            '${str(p['hours'])} × ${str(p['multiplier'])}',
            style: const TextStyle(fontWeight: FontWeight.w800),
          ),
        ),
      ];
    }
    if (a.kind == 'log_timesheet') {
      return [
        _detailRow('Who', Text(str(p['staff_name']))),
        _detailRow('Job', Text(str(p['job_name']))),
        _detailRow('When', Text(_longDate(str(p['date'])))),
        _detailRow(
          'Hours',
          Text(
            str(p['hours']),
            style: const TextStyle(fontWeight: FontWeight.w800),
          ),
        ),
        if (str(p['note']).isNotEmpty)
          _detailRow('Note', Text(str(p['note']))),
      ];
    }
    // log_mileage.
    return [
      _detailRow('Vehicle', Text(str(p['vehicle_name']))),
      _detailRow(
          'Journey', Text('${str(p['from'])} → ${str(p['to'])}')),
      _detailRow('When', Text(_longDate(str(p['date'])))),
      _detailRow(
        'Miles',
        Text(
          str(p['miles']),
          style: const TextStyle(fontWeight: FontWeight.w800),
        ),
      ),
      if (str(p['job_name']).isNotEmpty)
        _detailRow('Job', Text(str(p['job_name']))),
    ];
  }

  static String _vatLine(Map<String, dynamic> v) {
    final rate = v['vat_rate'];
    final code = (v['vat_code'] ?? '').toString();
    final name = code == 'O'
        ? 'outside the scope'
        : code == 'E'
            ? 'exempt'
            : 'zero rated';
    if (rate is num && rate != 0) {
      final pct = rate == rate.toInt() ? '${rate.toInt()}' : '$rate';
      return '$pct% on ${gbp(v['net_pence'] is num ? v['net_pence'] as num : 0)}';
    }
    return 'None ($name)';
  }

  /// A proposed action: what will happen, to whom, for how much. Nothing
  /// happens until Approve; the result line follows afterwards.
  Widget _actionCard(_Turn t) {
    final a = t.answer!.proposedAction!;
    final expires = a.expiresAt;
    final expired = expires != null && DateTime.now().isAfter(expires);
    final title = _actionTitles[a.kind] ?? 'Action';
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
          Text(
            'PROPOSED · ${title.toUpperCase()} · NEEDS YOUR OK',
            style: const TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: AccnomosColors.teal,
            ),
          ),
          const SizedBox(height: 8),
          ..._actionDetails(a),
          for (final w in a.warnings) ...[
            const SizedBox(height: 8),
            _warnBox(w),
          ],
          const SizedBox(height: 12),
          if (t.actionResult != null)
            Text(
              '✓ ${plain(t.actionResult!).replaceAll('**', '')}',
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

  /// A clarification: the question with the candidates as quick-reply chips
  /// that send the reply as the next turn.
  Widget _clarifyCard(_Turn t) {
    final c = t.answer!.clarification!;
    String plain(String md) => md
        .replaceAll(RegExp(r'^> ?', multiLine: true), '')
        .replaceAllMapped(RegExp(r'\\(.)'), (m) => m.group(1)!);
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
          ..._markdown(plain(c.questionMd)),
          if (c.candidates.isNotEmpty) ...[
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final name in c.candidates)
                  ActionChip(
                    label: Text(name),
                    onPressed: _busy
                        ? null
                        : () => _askQuestion(
                            withPicked(t.question, c, name)),
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
          Table(
            columnWidths: const {
              0: FlexColumnWidth(),
              1: IntrinsicColumnWidth(),
            },
            children: const [
              TableRow(
                children: [
                  Padding(
                    padding: EdgeInsets.only(
                        right: 12, top: 4, bottom: 4),
                    child: Text(
                      'Net VAT (Box 5), Q3',
                      style: TextStyle(
                          fontSize: 13,
                          color: AccnomosColors.muted),
                    ),
                  ),
                  Padding(
                    padding: EdgeInsets.only(top: 4, bottom: 4),
                    child: Text(
                      '£2,140.00',
                      textAlign: TextAlign.right,
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w800,
                        color: AccnomosColors.tealDark,
                      ),
                    ),
                  ),
                ],
              ),
              TableRow(
                children: [
                  Padding(
                    padding: EdgeInsets.only(
                        right: 12, top: 4, bottom: 4),
                    child: Text(
                      'Net VAT (Box 5), Q2',
                      style: TextStyle(
                          fontSize: 13,
                          color: AccnomosColors.muted),
                    ),
                  ),
                  Padding(
                    padding: EdgeInsets.only(top: 4, bottom: 4),
                    child: Text(
                      '£1,520.00',
                      textAlign: TextAlign.right,
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w800,
                        color: AccnomosColors.tealDark,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 8),
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
                  'Books.xlsx · VAT sheet',
                  style: TextStyle(fontSize: 12),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
            'numbers by code · explanation by Muse Spark · 1.2 s',
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
    final micOff = !live
        ? 'Sign in to ask by voice'
        : _busy || _sendingVoice
            ? 'Wait for the answer'
            : _voiceOff;
    final micActive = live && !_busy && !_sendingVoice && _voiceOff == null;
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
                    child: Tooltip(
                      message: micActive
                          ? 'Hold to ask by voice'
                          : (micOff ?? 'Voice unavailable'),
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
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: SizedBox(
                    height: 56,
                    child: TextField(
                      controller: _input,
                      focusNode: _focus,
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

/// One cited file: its OneDrive web URL (the Files screen's Open link)
/// when it resolves, otherwise the Books.xlsx sheet it feeds.
class _CitationChip extends StatefulWidget {
  const _CitationChip({required this.citation, this.sheet});

  final String citation;
  final String? sheet;

  @override
  State<_CitationChip> createState() => _CitationChipState();
}

class _CitationChipState extends State<_CitationChip> {
  final AuthService _auth = AuthService();
  final GraphService _graph = GraphService();
  String? _url;
  bool _tried = false;

  @override
  void dispose() {
    _graph.close();
    super.dispose();
  }

  Future<void> _resolve() async {
    if (_tried) return;
    _tried = true;
    try {
      final account = await _auth.account();
      if (account == null || !mounted) return;
      final token = await _auth.token();
      final url = await _graph.fileWebUrl(
        token,
        _auth.kind == AccountKind.work
            ? AccountKind.work
            : AccountKind.personal,
        widget.citation,
      );
      if (mounted) setState(() => _url = url);
    } catch (_) {
      // No link: the chip names the file instead.
    }
  }

  @override
  Widget build(BuildContext context) {
    final label = widget.sheet != null
        ? '${widget.citation} · ${widget.sheet} sheet'
        : widget.citation;
    return FutureBuilder<void>(
      future: _resolve(),
      builder: (context, _) {
        final url = _url;
        return ActionChip(
          label: Text(
            label,
            style: const TextStyle(fontSize: 12),
          ),
          tooltip: url != null
              ? 'Open ${widget.citation}'
              : widget.sheet != null
                  ? '${widget.citation}, ${widget.sheet} sheet'
                  : widget.citation,
          onPressed: url == null
              ? null
              : () async {
                  final launched = await launchUrl(
                    Uri.parse(url),
                    mode: LaunchMode.externalApplication,
                  );
                  if (!launched && context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                          content: Text('Could not open that file.')),
                    );
                  }
                },
        );
      },
    );
  }
}

/// A proposed day from `POST /plan/day`: timeline, rationale and warnings,
/// then Apply (with a confirmation; creates the new items as Outlook
/// events, asking for `Calendars.ReadWrite` only then) or Discard. Nothing
/// is written until Apply.
class _PlanSheet extends StatefulWidget {
  const _PlanSheet({
    required this.date,
    required this.settings,
    required this.auth,
    required this.account,
    required this.scroll,
  });

  final String date;
  final AppSettings settings;
  final AuthService auth;
  final Account? account;
  final ScrollController scroll;

  @override
  State<_PlanSheet> createState() => _PlanSheetState();
}

class _PlanSheetState extends State<_PlanSheet> {
  DayPlan? _plan;
  String? _error;
  bool _applying = false;
  AppliedPlan? _applied;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<RuntimeClient> _client({String? graphToken}) async {
    final account = widget.account;
    final user =
        account?.username ?? widget.settings.userEmail;
    return RuntimeClient(
      widget.settings,
      books: BooksAuth(
        graphToken: graphToken ?? await widget.auth.token(),
        accountKind: widget.auth.kind == AccountKind.work
            ? 'work'
            : 'personal',
        user: (user != null && user.isNotEmpty) ? user : null,
        businessName: widget.settings.businessName,
      ),
    );
  }

  Future<void> _load() async {
    try {
      // Calendars.Read is asked for here — the first time the user plans a
      // day — never at sign-in.
      final token =
          await widget.auth.tokenFor(AuthService.calendarReadScopes);
      final client = await _client(graphToken: token);
      final json = await client.planDay(
        date: widget.date,
        graphToken: token,
      );
      if (!mounted) return;
      setState(() => _plan = DayPlan.fromJson(json));
    } catch (e) {
      if (!mounted) return;
      setState(() =>
          _error = e.toString().replaceFirst('Exception: ', ''));
    }
  }

  /// Apply, after the confirmation dialog. `Calendars.ReadWrite` is asked
  /// for only on this tap.
  Future<void> _apply() async {
    final plan = _plan;
    if (plan == null || _applying) return;
    final confirm = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Add to Outlook?'),
        content: Text(
          'Add ${plan.fresh.length} '
          '${plan.fresh.length == 1 ? 'event' : 'events'} to your '
          'calendar, each marked [Accnomos]?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
                backgroundColor: AccnomosColors.teal),
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Add events'),
          ),
        ],
      ),
    );
    if (confirm != true || !mounted) return;
    setState(() {
      _applying = true;
      _error = null;
    });
    try {
      final token =
          await widget.auth.tokenFor(AuthService.calendarScopes);
      final client = await _client(graphToken: token);
      final json = await client.applyPlan(
        date: plan.date,
        plan: [for (final i in plan.items) i.toJson()],
        graphToken: token,
      );
      if (!mounted) return;
      setState(() => _applied = AppliedPlan.fromJson(json));
    } catch (e) {
      if (!mounted) return;
      setState(
          () => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _applying = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      child: ListView(
        controller: widget.scroll,
        children: [
          Center(
            child: Container(
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: const Color(0xFFE3E1D8),
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: Text(
                  'Plan for ${_AskScreenState._dayLabel(widget.date)}',
                  style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w800,
                    color: AccnomosColors.ink,
                  ),
                ),
              ),
              TextButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('Close'),
              ),
            ],
          ),
          const Text(
            'Order and times worked out by code from your calendar and '
            'open jobs.',
            style:
                TextStyle(fontSize: 13, color: AccnomosColors.muted),
          ),
          if (_plan == null && _error == null) ...[
            const SizedBox(height: 16),
            const Text(
              'Reading your calendar and jobs…',
              style: TextStyle(color: AccnomosColors.muted),
            ),
          ],
          if (_plan != null) ...[
            const SizedBox(height: 12),
            if (_plan!.items.isEmpty)
              const Text(
                'Nothing to plan for this day.',
                style: TextStyle(color: AccnomosColors.muted),
              )
            else
              for (final i in _plan!.items)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SizedBox(
                        width: 104,
                        child: Text(
                          '${_AskScreenState._clock(i.start)}–'
                          '${_AskScreenState._clock(i.end)}',
                          style: const TextStyle(
                            fontSize: 13,
                            color: AccnomosColors.ink,
                          ),
                        ),
                      ),
                      Expanded(
                        child: Column(
                          crossAxisAlignment:
                              CrossAxisAlignment.start,
                          children: [
                            Text(
                              i.title,
                              style: TextStyle(
                                fontSize: 15,
                                fontWeight: i.kind == 'visit'
                                    ? FontWeight.w800
                                    : FontWeight.w400,
                                color: AccnomosColors.ink,
                              ),
                            ),
                            if ((i.location ?? '').isNotEmpty)
                              Text(
                                i.location!,
                                style: const TextStyle(
                                  fontSize: 13,
                                  color: AccnomosColors.muted,
                                ),
                              ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
            if (_plan!.rationaleMd.isNotEmpty) ...[
              const SizedBox(height: 12),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: AccnomosColors.ground,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  _plan!.rationaleMd,
                  style: const TextStyle(
                      color: AccnomosColors.ink, height: 1.4),
                ),
              ),
            ],
            for (final w in _plan!.warnings) ...[
              const SizedBox(height: 8),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFFFFF7ED),
                  borderRadius: BorderRadius.circular(10),
                  border:
                      Border.all(color: const Color(0xFFF3C892)),
                ),
                child: Text(
                  w,
                  style: const TextStyle(
                      color: Color(0xFF8A3F06), height: 1.4),
                ),
              ),
            ],
            if (_applied != null)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(
                  _applied!.alreadyApplied
                      ? 'This plan is already in your calendar.'
                      : 'Added ${_applied!.created.length} '
                          '${_applied!.created.length == 1 ? 'event' : 'events'} '
                          'to your calendar, each marked [Accnomos].',
                  style: const TextStyle(
                    color: AccnomosColors.teal,
                    fontWeight: FontWeight.w700,
                    height: 1.4,
                  ),
                ),
              )
            else ...[
              const SizedBox(height: 12),
              Row(
                children: [
                  FilledButton(
                    style: FilledButton.styleFrom(
                        backgroundColor: AccnomosColors.teal),
                    onPressed: _applying || _plan!.fresh.isEmpty
                        ? null
                        : _apply,
                    child: Text(_applying
                        ? 'Adding…'
                        : 'Apply: add ${_plan!.fresh.length} '
                            '${_plan!.fresh.length == 1 ? 'event' : 'events'} '
                            'to Outlook'),
                  ),
                  const SizedBox(width: 8),
                  TextButton(
                    onPressed: () => Navigator.of(context).pop(),
                    child: const Text('Discard'),
                  ),
                ],
              ),
            ],
          ],
          if (_error != null) ...[
            const SizedBox(height: 12),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFFFFF7ED),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: const Color(0xFFF3C892)),
              ),
              child: Text(
                _error!,
                style: const TextStyle(
                    color: Color(0xFF8A3F06), height: 1.4),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
