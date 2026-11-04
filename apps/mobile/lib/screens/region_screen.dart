import 'package:flutter/material.dart';

import '../services/region.dart';
import '../services/runtime_client.dart';
import '../theme.dart';
import '../widgets/region_form.dart';

/// Settings › Country and tax: where the books are kept (GET/PUT /profile
/// `country`, `sales_tax`, `currency`), as the web's Connect › About your
/// business and Settings › Profile ask it. Outside the UK the app hides
/// every HMRC screen (VAT returns, payroll, MTD) and shows the books' own
/// currency and tax name.
class RegionScreen extends StatefulWidget {
  const RegionScreen({super.key, required this.clientFor});

  final Future<RuntimeClient> Function() clientFor;

  @override
  State<RegionScreen> createState() => _RegionScreenState();
}

class _RegionScreenState extends State<RegionScreen> {
  Map<String, dynamic>? _profile;
  RegionAnswers _answers = const RegionAnswers();
  bool _loading = true;
  bool _busy = false;
  String? _note;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final p = await (await widget.clientFor()).booksProfile();
      if (!mounted) return;
      setState(() {
        _profile = p;
        _answers = RegionAnswers.fromProfile(p);
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _note = '$e';
      });
    }
  }

  Future<void> _save() async {
    final problem = _answers.problem;
    if (problem != null) {
      setState(() => _note = problem);
      return;
    }
    final p = _profile;
    if (p == null || _busy) return;
    setState(() {
      _busy = true;
      _note = null;
    });
    try {
      final settings = Map<String, dynamic>.from((p['settings'] as Map?) ?? const {})
        ..remove('country')
        ..remove('currency')
        ..remove('sales_tax');
      final saved = await (await widget.clientFor()).saveBooksProfile({
        'name': p['name'] ?? 'My books',
        'kind': p['kind'] ?? 'company',
        'settings': {...settings, ..._answers.toSettings()},
      });
      // The shell (main.dart) and every money figure follow this at once.
      BooksRegion.current.value = BooksRegion.fromJson(saved['region']);
      if (!mounted) return;
      setState(() {
        _profile = saved;
        _answers = RegionAnswers.fromProfile(saved);
        _note = 'Saved to your OneDrive.';
      });
    } catch (e) {
      if (mounted) setState(() => _note = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(title: const Text('Country and tax')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                RegionForm(
                  value: _answers,
                  onChanged: (a) => setState(() {
                    _answers = a;
                    _note = null;
                  }),
                ),
                const SizedBox(height: 16),
                FilledButton(
                  key: const Key('region-save'),
                  style: FilledButton.styleFrom(
                    backgroundColor: AccnomosColors.teal,
                    minimumSize: const Size.fromHeight(48),
                  ),
                  onPressed: _busy || _profile == null ? null : _save,
                  child: Text(_busy ? 'Saving…' : 'Save'),
                ),
                if (_note != null) ...[
                  const SizedBox(height: 8),
                  Semantics(
                    liveRegion: true,
                    child: Text(_note!,
                        key: const Key('region-note'),
                        style: const TextStyle(color: AccnomosColors.tealDark)),
                  ),
                ],
              ],
            ),
    );
  }
}
