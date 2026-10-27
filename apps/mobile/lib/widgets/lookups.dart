import 'package:flutter/material.dart';

import '../services/books.dart';
import '../services/runtime_client.dart';
import '../theme.dart';

/// Where a VAT check answer came from, always shown with it (like the web's
/// `vatCheckSourceLabel` in `apps/web/src/lib/runtime.ts`).
String vatCheckSourceLabel(String source) {
  switch (source) {
    case 'hmrc':
      return 'HMRC';
    case 'hmrc-sandbox':
      return 'HMRC sandbox';
    default:
      return 'SAMPLE, test mode';
  }
}

/// The result line: who HMRC says the number is registered to, always with
/// where the answer came from (like the web's `vatCheckText`).
String vatCheckText(Map<String, dynamic> check) {
  final src = vatCheckSourceLabel((check['source'] ?? '').toString());
  if (check['registered'] != true) return 'Not VAT-registered ($src)';
  final who = [
    (check['name'] ?? '').toString().trim(),
    (check['address'] ?? '').toString().trim(),
  ].where((s) => s.isNotEmpty).join(', ');
  return 'Registered to ${who.isEmpty ? "a business HMRC didn't name" : who} ($src)';
}

/// "Look up on Companies House": search by name or number, then pick a match
/// to fill the form. [onSearch] returns the decoded `CompanySearch` items;
/// [onPick] fills the form (the caller saves). A 503
/// `companies_house_not_configured` calls [onNotConfigured] so the caller
/// hides the look-up instead of showing an error.
class CompanyLookupSection extends StatefulWidget {
  const CompanyLookupSection({
    super.key,
    required this.initialQuery,
    required this.onSearch,
    required this.onPick,
    this.onNotConfigured,
  });

  final String initialQuery;
  final Future<List<Map<String, dynamic>>> Function(String q) onSearch;
  final ValueChanged<Map<String, dynamic>> onPick;
  final VoidCallback? onNotConfigured;

  @override
  State<CompanyLookupSection> createState() => _CompanyLookupState();
}

class _CompanyLookupState extends State<CompanyLookupSection> {
  bool _open = false;
  final _q = TextEditingController();
  bool _busy = false;
  List<Map<String, dynamic>>? _items;
  String? _error;

  @override
  void initState() {
    super.initState();
    _q.text = widget.initialQuery;
  }

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  Future<void> _search() async {
    if (_q.text.trim().length < 2) {
      setState(() => _error =
          'Type at least 2 characters of the name, or the company number.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final items = await widget.onSearch(_q.text.trim());
      if (!mounted) return;
      setState(() => _items = items);
    } catch (e) {
      if (!mounted) return;
      if (RuntimeClient.lookupNotConfigured(
          e, 'companies_house_not_configured')) {
        widget.onNotConfigured?.call();
        return;
      }
      setState(() {
        _items = null;
        _error = _short(e);
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!_open) {
      return Align(
        alignment: Alignment.centerLeft,
        child: OutlinedButton(
          style: OutlinedButton.styleFrom(
            foregroundColor: AccnomosColors.tealDark,
            side: const BorderSide(
                color: AccnomosColors.teal, width: 2),
            minimumSize: const Size(48, 48),
          ),
          onPressed: () => setState(() => _open = true),
          child: const Text('Look up on Companies House'),
        ),
      );
    }
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AccnomosColors.ground,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Company name or number',
            style: TextStyle(
                fontWeight: FontWeight.w700,
                fontSize: 13,
                color: AccnomosColors.muted),
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _q,
                  decoration: const InputDecoration(
                    border: OutlineInputBorder(),
                    filled: true,
                    fillColor: Colors.white,
                  ),
                  onSubmitted: (_) => _search(),
                ),
              ),
              const SizedBox(width: 8),
              FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size(48, 48),
                ),
                onPressed: _busy ? null : _search,
                child: Text(_busy ? 'Looking…' : 'Look up'),
              ),
            ],
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(_error!,
                  style: const TextStyle(
                      color: Color(0xFF8A3F06),
                      fontWeight: FontWeight.w600)),
            ),
          if (_items != null)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                _items!.isEmpty
                    ? 'No companies found.'
                    : '${_items!.length} found. Pick one to fill the name, company number and address; nothing is saved until you press Save.',
                style: const TextStyle(
                    fontSize: 13, color: AccnomosColors.muted),
              ),
            ),
          if (_items != null && _items!.isNotEmpty)
            for (final m in _items!)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: SizedBox(
                  width: double.infinity,
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      alignment: Alignment.centerLeft,
                      foregroundColor: AccnomosColors.ink,
                      backgroundColor: Colors.white,
                      minimumSize: const Size(48, 48),
                    ),
                    onPressed: () {
                      widget.onPick(m);
                      setState(() => _open = false);
                    },
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text((m['name'] ?? '').toString(),
                            style: const TextStyle(
                                fontWeight: FontWeight.w700)),
                        Text(
                          [
                            (m['company_number'] ?? '').toString(),
                            (m['status'] ?? '').toString(),
                            (m['address'] ?? '').toString(),
                          ].where((s) => s.isNotEmpty).join(' · '),
                          style: const TextStyle(
                              fontSize: 13,
                              color: AccnomosColors.muted),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
          TextButton(
            style: TextButton.styleFrom(
              foregroundColor: AccnomosColors.tealDark,
              minimumSize: const Size(48, 48),
            ),
            onPressed: () => setState(() => _open = false),
            child: const Text('Close look-up'),
          ),
        ],
      ),
    );
  }
}

/// "Check VAT number": asks HMRC only when tapped, then shows who the number
/// is registered to. A name that differs is a warning, never a block.
/// [onCheck] returns the decoded `VatCheckResult`. A 503
/// `vat_check_not_configured` calls [onNotConfigured] so the caller hides
/// the check instead of showing an error.
class VatCheckSection extends StatefulWidget {
  const VatCheckSection({
    super.key,
    required this.vrn,
    required this.name,
    required this.onCheck,
    this.contactId,
    this.initial,
    this.onChecked,
    this.onNotConfigured,
  });

  final String vrn;
  final String name;
  final Future<Map<String, dynamic>> Function() onCheck;
  final String? contactId;
  final Map<String, dynamic>? initial;
  final VoidCallback? onChecked;
  final VoidCallback? onNotConfigured;

  @override
  State<VatCheckSection> createState() => _VatCheckState();
}

class _VatCheckState extends State<VatCheckSection> {
  Map<String, dynamic>? _check;
  bool _differs = false;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _check = widget.initial;
  }

  Future<void> _run() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await widget.onCheck();
      if (!mounted) return;
      final check = result['check'];
      setState(() {
        _check =
            check is Map ? Map<String, dynamic>.from(check) : null;
        _differs = result['name_differs'] == true;
      });
      if (result['cached'] != true) widget.onChecked?.call();
    } catch (e) {
      if (!mounted) return;
      if (RuntimeClient.lookupNotConfigured(e, 'vat_check_not_configured')) {
        widget.onNotConfigured?.call();
        return;
      }
      setState(() => _error = _short(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton(
            style: OutlinedButton.styleFrom(
              foregroundColor: AccnomosColors.tealDark,
              side: const BorderSide(
                  color: AccnomosColors.teal, width: 2),
              minimumSize: const Size(48, 48),
            ),
            onPressed: _busy ? null : _run,
            child: Text(_busy ? 'Checking…' : 'Check VAT number'),
          ),
        ),
        if (_check != null)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  vatCheckText(_check!),
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    color: _check!['registered'] == true
                        ? AccnomosColors.ink
                        : const Color(0xFF8A3F06),
                  ),
                ),
                if (((_check!['checked_at'] ?? '').toString().length >=
                    10))
                  Text(
                    'Checked ${ukDate((_check!['checked_at'] ?? '').toString().substring(0, 10))}'
                    '${(_check!['consultation_number'] ?? '').toString().isNotEmpty ? ' · HMRC reference ${(_check!['consultation_number'] ?? '').toString()}' : ''}',
                    style: const TextStyle(
                        fontSize: 13,
                        color: AccnomosColors.muted),
                  ),
                if (_check!['registered'] == true && _differs)
                  Container(
                    margin: const EdgeInsets.only(top: 6),
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFDF3E7),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(
                          color: const Color(0xFFE8CFA8)),
                    ),
                    child: Text(
                      "HMRC's name differs from ${widget.name}. Check it's the same business before you rely on this VAT number.",
                      style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: Color(0xFF8A3F06)),
                    ),
                  ),
              ],
            ),
          ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(_error!,
                style: const TextStyle(
                    fontSize: 13,
                    color: Color(0xFF8A3F06),
                    fontWeight: FontWeight.w600)),
          ),
      ],
    );
  }
}

String _short(Object e) {
  final text = e.toString().replaceAll(RegExp(r' \(status \d+[^)]*\)'), '');
  return text.length > 200 ? '${text.substring(0, 200)}…' : text;
}
