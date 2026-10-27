import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/proposal_editing.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../services/sign_in_messages.dart';
import '../theme.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);

/// Reader + AI settings. Opened from the gear icon in the Home app bar.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _auth = AuthService();
  final _runtimeUrl = TextEditingController();
  final _aiBaseUrl = TextEditingController();
  final _aiModel = TextEditingController();
  final _apiKey = TextEditingController();
  final _businessName = TextEditingController();
  final _vrn = TextEditingController();
  String? _vrnError;
  final _startMonth = TextEditingController();
  String? _startMonthError;
  int _stagger = 1;

  AppSettings? _initial;
  Account? _account;
  String _mode = 'local';
  bool _obscureKey = true;
  bool _testing = false;
  bool _saving = false;
  bool _authBusy = false;
  String? _testMessage;
  bool _testOk = false;
  String? _authError;

  @override
  void initState() {
    super.initState();
    AppSettings.load().then((settings) {
      if (!mounted) return;
      setState(() {
        _initial = settings;
        _runtimeUrl.text = settings.runtimeUrl;
        _aiBaseUrl.text = settings.aiBaseUrl;
        _aiModel.text = settings.aiModel;
        _apiKey.text = settings.apiKey ?? '';
        _businessName.text = settings.businessName ?? '';
        _vrn.text = settings.vatNumber ?? '';
        _mode = settings.aiMode;
        _stagger = settings.vatStagger;
        _startMonth.text = settings.vatStartMonth?.toString() ?? '';
      });
    });
    _auth.account().then((account) {
      if (!mounted) return;
      setState(() => _account = account);
    }).catchError((Object _) => null);
  }

  @override
  void dispose() {
    _runtimeUrl.dispose();
    _aiBaseUrl.dispose();
    _aiModel.dispose();
    _apiKey.dispose();
    _businessName.dispose();
    _vrn.dispose();
    _startMonth.dispose();
    super.dispose();
  }

  /// Month 1–12 from the custom start-month field, or null when empty.
  /// Out-of-range text returns -1 so saving can flag it.
  int? _startMonthValue() {
    final text = _startMonth.text.trim();
    if (text.isEmpty) return null;
    final month = int.tryParse(text);
    if (month == null || month < 1 || month > 12) return -1;
    return month;
  }

  AppSettings _current() => AppSettings(
        runtimeUrl: _runtimeUrl.text.trim(),
        aiMode: _mode,
        aiBaseUrl: _aiBaseUrl.text.trim(),
        aiModel: _aiModel.text.trim(),
        apiKey:
            _apiKey.text.trim().isEmpty ? null : _apiKey.text.trim(),
        userEmail: _initial?.userEmail,
        businessName: _businessName.text.trim().isEmpty
            ? null
            : _businessName.text.trim(),
        vatNumber: _vrn.text.trim().isEmpty ? null : _vrn.text.trim(),
        vatStagger: _stagger,
        vatStartMonth: _startMonthValue() == -1 ? null : _startMonthValue(),
      );

  Future<void> _signIn() async {
    if (_authBusy) return;
    setState(() {
      _authBusy = true;
      _authError = null;
    });
    try {
      final account = await _auth.signIn();
      if (!mounted) return;
      setState(() => _account = account);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content: Text(
                'Signed in as ${AuthService.displayName(account)}')),
      );
    } catch (e) {
      if (!mounted) return;
      // Never a raw exception: map MSAL failures to plain English.
      setState(() => _authError = friendlySignInMessage(e));
    } finally {
      if (mounted) setState(() => _authBusy = false);
    }
  }

  Future<void> _signOut() async {
    if (_authBusy) return;
    setState(() {
      _authBusy = true;
      _authError = null;
    });
    try {
      await _auth.signOut();
      if (!mounted) return;
      setState(() => _account = null);
    } catch (e) {
      if (!mounted) return;
      setState(() => _authError = friendlySignInMessage(e));
    } finally {
      if (mounted) setState(() => _authBusy = false);
    }
  }

  Future<void> _test() async {
    if (_testing) return;
    setState(() {
      _testing = true;
      _testMessage = null;
    });
    try {
      final result = await RuntimeClient(_current()).aiTest();
      if (!mounted) return;
      setState(() {
        _testOk = true;
        _testMessage = 'Connected. The reader answered: $result';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _testOk = false;
        _testMessage = e.toString();
      });
    } finally {
      if (mounted) setState(() => _testing = false);
    }
  }

  Future<void> _save() async {
    if (_saving) return;
    final vrnProblem = vrnError(_vrn.text);
    if (vrnProblem != null) {
      setState(() => _vrnError = vrnProblem);
      return;
    }
    if (_startMonthValue() == -1) {
      setState(() =>
          _startMonthError = 'Enter a month 1–12, or leave it empty.');
      return;
    }
    setState(() {
      _vrnError = null;
      _startMonthError = null;
      _saving = true;
    });
    await _current().save();
    if (!mounted) return;
    setState(() => _saving = false);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Settings saved')),
    );
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          'Settings',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
      ),
      body: _initial == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _accountCard(),
                const SizedBox(height: 16),
                _field(
                  label: 'Business name',
                  helper: 'Sent as X-Business-Name so the reader '
                      'attributes sales to your business.',
                  controller: _businessName,
                ),
                const SizedBox(height: 16),
                _field(
                  label: 'VAT number',
                  helper: 'Your 9-digit VAT registration number, e.g. '
                      '123456789. Checked for format only.',
                  controller: _vrn,
                  error: _vrnError,
                  onChanged: (_) {
                    if (_vrnError != null) {
                      setState(() => _vrnError = vrnError(_vrn.text));
                    }
                  },
                ),
                const SizedBox(height: 16),
                const Text('VAT quarter',
                    style: TextStyle(
                        fontWeight: FontWeight.w700,
                        color: AccnomosColors.ink)),
                const SizedBox(height: 4),
                const Text(
                    'Your HMRC stagger group. The Home tab uses it for the next VAT deadline.',
                    style: TextStyle(
                        color: AccnomosColors.muted,
                        fontSize: 12,
                        height: 1.4)),
                const SizedBox(height: 8),
                SegmentedButton<int>(
                  segments: const [
                    ButtonSegment(value: 1, label: Text('1')),
                    ButtonSegment(value: 2, label: Text('2')),
                    ButtonSegment(value: 3, label: Text('3')),
                  ],
                  selected: {_stagger},
                  onSelectionChanged: (selected) =>
                      setState(() => _stagger = selected.first),
                ),
                const SizedBox(height: 16),
                _field(
                  label: 'Quarter starts in month (optional)',
                  helper: 'Only when your quarters start in a custom '
                      'month, e.g. 5 for May. Takes precedence over the stagger group above.',
                  controller: _startMonth,
                  error: _startMonthError,
                  onChanged: (_) {
                    if (_startMonthError != null) {
                      setState(() => _startMonthError = null);
                    }
                  },
                ),
                const SizedBox(height: 16),
                _field(
                  label: 'Reader address',
                  helper: 'The computer that reads your receipts. On the '
                      'Android emulator, http://10.0.2.2:8780 means your '
                      'own PC.',
                  controller: _runtimeUrl,
                ),
                const SizedBox(height: 16),
                const Text('Where should the reading happen?',
                    style: TextStyle(
                        fontWeight: FontWeight.w700,
                        color: AccnomosColors.ink)),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                        child: _modeButton('local', 'On your machine',
                            Icons.computer_outlined)),
                    const SizedBox(width: 8),
                    Expanded(
                        child: _modeButton('key', 'Muse Spark (key)',
                            Icons.bolt_outlined)),
                  ],
                ),
                const SizedBox(height: 16),
                _field(
                  label: 'Local AI address',
                  helper: 'Where your on-machine model listens.',
                  controller: _aiBaseUrl,
                ),
                const SizedBox(height: 16),
                _field(
                  label: 'Local model name',
                  helper: 'The model the reader asks on your machine.',
                  controller: _aiModel,
                ),
                const SizedBox(height: 16),
                _field(
                  label: 'Muse API key',
                  helper: 'Only used when “Muse Spark (key)” is chosen. '
                      'TODO: move to secure storage.',
                  controller: _apiKey,
                  obscure: _obscureKey,
                  suffix: IconButton(
                    constraints:
                        const BoxConstraints(minWidth: 48, minHeight: 48),
                    icon: Icon(_obscureKey
                        ? Icons.visibility_outlined
                        : Icons.visibility_off_outlined),
                    tooltip: _obscureKey ? 'Show key' : 'Hide key',
                    onPressed: () =>
                        setState(() => _obscureKey = !_obscureKey),
                  ),
                ),
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(48),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14)),
                    ),
                    onPressed: _testing ? null : _test,
                    child: _testing
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Text('Test connection'),
                  ),
                ),
                if (_testMessage != null) ...[
                  const SizedBox(height: 8),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color:
                          _testOk ? AccnomosColors.tealTint : _warnBg,
                      borderRadius: BorderRadius.circular(10),
                      border: _testOk
                          ? null
                          : Border.all(color: _warnBorder),
                    ),
                    child: Text(
                      _testMessage!,
                      style: TextStyle(
                        color: _testOk
                            ? AccnomosColors.tealDark
                            : _warnInk,
                        height: 1.4,
                      ),
                    ),
                  ),
                ],
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    style: FilledButton.styleFrom(
                      backgroundColor: AccnomosColors.teal,
                      minimumSize: const Size.fromHeight(52),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14)),
                    ),
                    onPressed: _saving ? null : _save,
                    child: const Text('Save',
                        style: TextStyle(
                            fontWeight: FontWeight.w800, fontSize: 16)),
                  ),
                ),
              ],
            ),
    );
  }

  Widget _accountCard() {
    final account = _account;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Microsoft account',
              style: TextStyle(
                  fontWeight: FontWeight.w700,
                  color: AccnomosColors.ink)),
          const SizedBox(height: 4),
          Text(
            account == null
                ? 'Your books live in your own OneDrive. Sign in to see them.'
                : 'Signed in as ${AuthService.displayName(account)}',
            style: const TextStyle(
                color: AccnomosColors.muted, fontSize: 12, height: 1.4),
          ),
          if (_authError != null) ...[
            const SizedBox(height: 8),
            Text(_authError!,
                style: const TextStyle(color: _warnInk, height: 1.4)),
          ],
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: account == null
                ? FilledButton(
                    style: FilledButton.styleFrom(
                      backgroundColor: AccnomosColors.teal,
                      minimumSize: const Size.fromHeight(52),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14)),
                    ),
                    onPressed: _authBusy ? null : _signIn,
                    child: _authBusy
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(
                                strokeWidth: 2, color: Colors.white),
                          )
                        : const Text('Sign in with Microsoft',
                            style: TextStyle(
                                fontWeight: FontWeight.w800,
                                fontSize: 16)),
                  )
                : OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(52),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14)),
                    ),
                    onPressed: _authBusy ? null : _signOut,
                    child: const Text('Sign out'),
                  ),
          ),
        ],
      ),
    );
  }

  Widget _modeButton(String value, String label, IconData icon) {
    final selected = _mode == value;
    final shape = RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14));
    if (selected) {
      return FilledButton.icon(
        style: FilledButton.styleFrom(
          backgroundColor: AccnomosColors.teal,
          minimumSize: const Size.fromHeight(48),
          shape: shape,
        ),
        onPressed: () => setState(() => _mode = value),
        icon: Icon(icon),
        label: Text(label,
            style: const TextStyle(fontWeight: FontWeight.w700)),
      );
    }
    return OutlinedButton.icon(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size.fromHeight(48),
        shape: shape,
      ),
      onPressed: () => setState(() => _mode = value),
      icon: Icon(icon),
      label: Text(label,
          style: const TextStyle(fontWeight: FontWeight.w700)),
    );
  }

  Widget _field({
    required String label,
    required String helper,
    required TextEditingController controller,
    bool obscure = false,
    Widget? suffix,
    String? error,
    ValueChanged<String>? onChanged,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: const TextStyle(
                fontWeight: FontWeight.w700, color: AccnomosColors.ink)),
        const SizedBox(height: 6),
        TextField(
          controller: controller,
          obscureText: obscure,
          autocorrect: false,
          onChanged: onChanged,
          decoration: InputDecoration(
            filled: true,
            fillColor: Colors.white,
            contentPadding: const EdgeInsets.symmetric(
                horizontal: 16, vertical: 16),
            border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(14)),
            suffixIcon: suffix,
            errorText: error,
          ),
        ),
        const SizedBox(height: 4),
        Text(helper,
            style: const TextStyle(
                color: AccnomosColors.muted, fontSize: 12, height: 1.4)),
      ],
    );
  }
}
