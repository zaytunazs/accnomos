import 'package:flutter/material.dart';

import '../services/runtime_client.dart';
import '../services/settings.dart';
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
  final _runtimeUrl = TextEditingController();
  final _aiBaseUrl = TextEditingController();
  final _aiModel = TextEditingController();
  final _apiKey = TextEditingController();

  AppSettings? _initial;
  String _mode = 'local';
  bool _obscureKey = true;
  bool _testing = false;
  bool _saving = false;
  String? _testMessage;
  bool _testOk = false;

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
        _mode = settings.aiMode;
      });
    });
  }

  @override
  void dispose() {
    _runtimeUrl.dispose();
    _aiBaseUrl.dispose();
    _aiModel.dispose();
    _apiKey.dispose();
    super.dispose();
  }

  AppSettings _current() => AppSettings(
        runtimeUrl: _runtimeUrl.text.trim(),
        aiMode: _mode,
        aiBaseUrl: _aiBaseUrl.text.trim(),
        aiModel: _aiModel.text.trim(),
        apiKey:
            _apiKey.text.trim().isEmpty ? null : _apiKey.text.trim(),
        userEmail: _initial?.userEmail,
      );

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
    setState(() => _saving = true);
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
          decoration: InputDecoration(
            filled: true,
            fillColor: Colors.white,
            contentPadding: const EdgeInsets.symmetric(
                horizontal: 16, vertical: 16),
            border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(14)),
            suffixIcon: suffix,
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
