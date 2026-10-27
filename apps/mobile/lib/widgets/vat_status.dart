import 'package:flutter/material.dart';

import '../theme.dart';

/// Wire values for `Contact.vat_status`
/// (`services/runtime/app/contacts.py`, `VatStatus` in `schemas.py`).
const vatStatusUnknown = 'unknown';
const vatStatusRegistered = 'registered';
const vatStatusNotRegistered = 'not_registered';

/// Short labels for the list chips and the detail control.
String vatStatusLabel(String status) {
  switch (status) {
    case vatStatusRegistered:
      return 'VAT-registered';
    case vatStatusNotRegistered:
      return 'Not VAT-registered';
    default:
      return 'Not known';
  }
}

/// UK VAT number check, same as the web's `isVrnValid` in
/// `apps/web/src/components/contacts/LiveContacts.tsx`: GB followed by 9
/// or 12 digits; spaces are allowed and ignored. Empty is not valid here —
/// callers treat blank as "no VAT number" before calling this.
bool isValidContactVrn(String text) {
  final cleaned =
      text.trim().toUpperCase().replaceAll(RegExp(r'\s+'), '');
  return RegExp(r'^GB\d{9}(\d{3})?$').hasMatch(cleaned);
}

/// VAT status as a three-way segmented control (unknown / registered /
/// not registered). Fits a 360 dp phone: short labels, no selected icon.
class VatStatusSegmented extends StatelessWidget {
  const VatStatusSegmented({
    super.key,
    required this.value,
    required this.onChanged,
    this.autofocus = false,
    this.enabled = true,
  });

  /// One of the `vatStatus*` wire values.
  final String value;
  final ValueChanged<String> onChanged;
  final bool autofocus;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return Focus(
      autofocus: autofocus,
      child: SegmentedButton<String>(
        segments: const [
          ButtonSegment(
            value: vatStatusUnknown,
            label: Text('Not known'),
          ),
          ButtonSegment(
            value: vatStatusRegistered,
            label: Text('Registered'),
          ),
          ButtonSegment(
            value: vatStatusNotRegistered,
            label: Text('Not registered'),
          ),
        ],
        selected: {value},
        emptySelectionAllowed: false,
        showSelectedIcon: false,
        onSelectionChanged:
            enabled ? (selected) => onChanged(selected.first) : null,
        style: SegmentedButton.styleFrom(
          textStyle: const TextStyle(fontSize: 13),
          visualDensity: VisualDensity.compact,
        ),
      ),
    );
  }
}

/// Small chip for the contacts list: "VAT-registered" or
/// "Not VAT-registered"; nothing when the status is unknown.
class VatStatusChip extends StatelessWidget {
  const VatStatusChip({super.key, required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    if (status != vatStatusRegistered &&
        status != vatStatusNotRegistered) {
      return const SizedBox.shrink();
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: AccnomosColors.tealTint,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        vatStatusLabel(status),
        style: const TextStyle(
          color: AccnomosColors.tealDark,
          fontSize: 12,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}
