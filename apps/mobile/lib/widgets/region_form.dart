import 'package:flutter/material.dart';

import '../services/region.dart';
import '../theme.dart';

/// The answers [RegionForm] collects: where the books are kept, the tax the
/// business charges and its rate, and the currency (the runtime's profile
/// `country`, `sales_tax` and `currency`, services/runtime/app/profile.py).
@immutable
class RegionAnswers {
  const RegionAnswers({
    this.country = 'GB',
    this.taxName = 'VAT',
    this.taxRate = 20,
    this.currency = 'GBP',
  });

  final String country;
  final String taxName;
  final num taxRate;
  final String currency;

  bool get uk => country == 'GB';

  /// A newly chosen country starts from its usual tax, rate and currency.
  factory RegionAnswers.forCountry(String country) {
    if (country == 'GB') return const RegionAnswers();
    final (name, rate) = defaultTax(country);
    return RegionAnswers(
      country: country,
      taxName: name,
      taxRate: rate,
      currency: defaultCurrency(country) ?? '',
    );
  }

  /// From GET /profile (UK books when it says nothing else).
  factory RegionAnswers.fromProfile(Map<String, dynamic>? profile) {
    final r = BooksRegion.fromJson(profile?['region']);
    if (r.uk) return const RegionAnswers();
    final tax = (profile?['settings'] as Map?)?['sales_tax'];
    return RegionAnswers(
      country: r.country,
      taxName: tax is Map ? '${tax['name'] ?? r.taxName}' : r.taxName,
      taxRate: r.taxRate,
      currency: r.currency,
    );
  }

  RegionAnswers copyWith({String? taxName, num? taxRate, String? currency}) =>
      RegionAnswers(
        country: country,
        taxName: taxName ?? this.taxName,
        taxRate: taxRate ?? this.taxRate,
        currency: currency ?? this.currency,
      );

  /// The profile settings for these answers; UK books send only the country.
  Map<String, dynamic> toSettings() => uk
      ? {'country': 'GB'}
      : {
          'country': country,
          'currency': currency,
          'sales_tax': {
            'name': taxName,
            'rate_percent': taxName == 'None' ? 0 : taxRate,
          },
        };

  /// A sentence when these cannot be saved, else null.
  String? get problem {
    if (uk) return null;
    if (currency.isEmpty) return 'Choose the currency your books are kept in.';
    if (taxName != 'None' && !(taxRate >= 0 && taxRate <= 100)) {
      return 'Enter a percentage from 0 to 100.';
    }
    return null;
  }
}

/// Country first (searchable, the UK by default); outside the UK: "Do you
/// charge VAT, GST or sales tax?", "What percentage?" (prefilled with the
/// country's usual rate) and the currency (prefilled where known). The same
/// questions as the web's components/onboarding/RegionFields.tsx.
class RegionForm extends StatefulWidget {
  const RegionForm({super.key, required this.value, required this.onChanged});

  final RegionAnswers value;
  final ValueChanged<RegionAnswers> onChanged;

  @override
  State<RegionForm> createState() => _RegionFormState();
}

class _RegionFormState extends State<RegionForm> {
  final _search = TextEditingController();
  late final _rate = TextEditingController(text: _rateText(widget.value.taxRate));

  static String _rateText(num r) =>
      r == r.roundToDouble() ? r.toInt().toString() : r.toString();

  @override
  void didUpdateWidget(RegionForm old) {
    super.didUpdateWidget(old);
    if (old.value.country != widget.value.country) {
      _rate.text = _rateText(widget.value.taxRate);
    }
  }

  @override
  void dispose() {
    _search.dispose();
    _rate.dispose();
    super.dispose();
  }

  List<(String, String)> get _shown {
    final q = _search.text.trim().toLowerCase();
    final hits = q.isEmpty
        ? countries
        : [
            for (final c in countries)
              if (c.$2.toLowerCase().contains(q) || c.$1.toLowerCase() == q) c,
          ];
    final chosen = widget.value.country;
    return hits.any((c) => c.$1 == chosen)
        ? hits
        : [(chosen, countryNameOf(chosen)), ...hits];
  }

  void _pickCountry(String code) {
    if (code != widget.value.country) {
      widget.onChanged(RegionAnswers.forCountry(code));
    }
  }

  @override
  Widget build(BuildContext context) {
    final v = widget.value;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TextField(
          key: const Key('region-search'),
          controller: _search,
          decoration: const InputDecoration(
            labelText: 'Search countries',
            prefixIcon: Icon(Icons.search),
          ),
          onChanged: (text) {
            setState(() {});
            final q = text.trim().toLowerCase();
            for (final (code, name) in countries) {
              if (name.toLowerCase() == q) _pickCountry(code);
            }
          },
        ),
        const SizedBox(height: 8),
        DropdownButtonFormField<String>(
          key: ValueKey('region-country-${v.country}'),
          initialValue: v.country,
          isExpanded: true,
          decoration: const InputDecoration(labelText: 'Country'),
          items: [
            for (final (code, name) in _shown)
              DropdownMenuItem(value: code, child: Text(name)),
          ],
          onChanged: (code) {
            if (code != null) _pickCountry(code);
          },
        ),
        const SizedBox(height: 6),
        Text(
          v.uk
              ? 'UK books: VAT returns, payroll and MTD filing with HMRC are all here.'
              : 'Bookkeeping, invoices, reports and CSV exports work the same everywhere. '
                  'HMRC filing (VAT returns, payroll, MTD) is for UK books, so it stays hidden.',
          style: const TextStyle(color: AccnomosColors.muted, fontSize: 12, height: 1.4),
        ),
        if (!v.uk) ...[
          const SizedBox(height: 16),
          const Text('Do you charge VAT, GST or sales tax?',
              style: TextStyle(fontWeight: FontWeight.w700, color: AccnomosColors.ink)),
          const SizedBox(height: 6),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final name in taxNames)
                ChoiceChip(
                  key: Key('region-tax-$name'),
                  label: Text(name == 'None' ? "None — I don't charge tax" : name),
                  selected: v.taxName == name,
                  onSelected: (_) => widget.onChanged(v.copyWith(taxName: name)),
                ),
            ],
          ),
          if (v.taxName != 'None') ...[
            const SizedBox(height: 12),
            TextField(
              key: const Key('region-rate'),
              controller: _rate,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                labelText: 'What percentage?',
                suffixText: '%',
                helperText: 'Your standard rate. New invoice lines use it.',
              ),
              onChanged: (text) =>
                  widget.onChanged(v.copyWith(taxRate: num.tryParse(text.trim()) ?? double.nan)),
            ),
          ],
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            key: ValueKey('region-currency-${v.country}'),
            initialValue: v.currency.isEmpty ? null : v.currency,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Currency'),
            items: [
              for (final (code, name) in currencies)
                DropdownMenuItem(value: code, child: Text('$name ($code)')),
            ],
            onChanged: (code) {
              if (code != null) widget.onChanged(v.copyWith(currency: code));
            },
          ),
        ],
      ],
    );
  }
}
