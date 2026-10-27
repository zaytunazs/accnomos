import 'package:flutter/services.dart';

/// One contact returned by the phone's system contact picker.
///
/// Read-only: the picker hands back a single contact URI with a one-time
/// grant, and Android reads the name, emails, phones and first postal
/// address from that URI only. Nothing is written back to the phone, and
/// the app holds no `READ_CONTACTS` permission.
class PickedPhoneContact {
  PickedPhoneContact({
    required this.name,
    this.emails = const [],
    this.phones = const [],
    this.address,
  });

  final String name;
  final List<String> emails;
  final List<String> phones;
  final String? address;

  String get email => emails.isEmpty ? '' : emails.first;
  String get phone => phones.isEmpty ? '' : phones.first;

  /// The review sheet body for `POST /contacts/import-phone`.
  Map<String, String?> toImportJson(String kind) => {
        'name': name,
        'kind': kind,
        if (email.isNotEmpty) 'email': email,
        if (phone.isNotEmpty) 'phone': phone,
        if ((address ?? '').trim().isNotEmpty) 'address': address!.trim(),
      };
}

/// Opens Android's system contact picker. The channel is served by
/// `MainActivity` (`accnomos/phone-contacts`); [channel] exists so widget
/// tests can mock the picker.
class PhoneContacts {
  PhoneContacts({MethodChannel? channel})
      : channel = channel ?? const MethodChannel('accnomos/phone-contacts');

  final MethodChannel channel;

  /// Show the picker once. Returns null when the user backs out.
  Future<PickedPhoneContact?> pickContact() async {
    final raw = await channel.invokeMethod<Map<Object?, Object?>>(
        'pickContact');
    if (raw == null) return null;
    final map = Map<String, dynamic>.from(
        raw.map((key, value) => MapEntry(key.toString(), value)));
    final name = (map['name'] ?? '').toString().trim();
    if (name.isEmpty) return null;
    List<String> strings(Object? value) => [
          if (value is List)
            for (final v in value)
              if (v.toString().trim().isNotEmpty) v.toString().trim(),
        ];
    final address = (map['address'] ?? '').toString().trim();
    return PickedPhoneContact(
      name: name,
      emails: strings(map['emails']),
      phones: strings(map['phones']),
      address: address.isEmpty ? null : address,
    );
  }
}
