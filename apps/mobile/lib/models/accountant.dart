/// Your accountant and their queries, as the runtime returns them
/// (services/runtime/app/accountant.py and queries.py). Read-only here.
library;

class AccountantAccess {
  AccountantAccess({
    required this.email,
    required this.name,
    required this.team,
    required this.canEdit,
    required this.manual,
    required this.since,
  });

  final String email;
  final String name;
  final bool team; // the Accnomos accountants opt-in
  final bool canEdit;
  final bool manual; // shared by the client in OneDrive, only recorded here
  final DateTime? since;

  String get who => name.isNotEmpty ? '$name ($email)' : email;
  String get access => canEdit ? 'View and edit' : 'View only';

  /// Active invitations only (a revoked one has `revoked_at`).
  static List<AccountantAccess> activeFrom(Map<String, dynamic> settings) {
    final raw = settings['invitations'];
    if (raw is! List) return const [];
    return [
      for (final i in raw)
        if (i is Map && i['revoked_at'] == null)
          AccountantAccess(
            email: (i['email'] ?? '').toString(),
            name: (i['name'] ?? '').toString(),
            team: i['kind'] == 'team',
            canEdit: i['role'] == 'edit',
            manual: i['method'] == 'manual',
            since: DateTime.tryParse((i['invited_at'] ?? '').toString())
                ?.toLocal(),
          ),
    ];
  }
}

class QueryMessage {
  QueryMessage({
    required this.fromAccountant,
    required this.author,
    required this.text,
    required this.at,
  });

  final bool fromAccountant;
  final String author;
  final String text;
  final DateTime? at;
}

class ClientQuery {
  ClientQuery({
    required this.id,
    required this.about,
    required this.open,
    required this.waitingOnYou,
    required this.messages,
  });

  final String id;
  final String about; // "A Review card: Novex · £51.90"
  final bool open;
  final bool waitingOnYou; // the client is the phone's user
  final List<QueryMessage> messages;

  static const _kinds = {
    'transaction': 'A transaction',
    'document': 'A document',
    'proposal': 'A Review card',
    'bank_line': 'A bank line',
    'invoice': 'An invoice',
    'general': 'The books in general',
  };

  static ClientQuery? fromJson(Map<String, dynamic> j) {
    final id = (j['id'] ?? '').toString();
    if (id.isEmpty) return null;
    final subject = j['subject'] is Map
        ? Map<String, dynamic>.from(j['subject'] as Map)
        : <String, dynamic>{};
    final kind = _kinds[subject['kind']] ?? 'The books in general';
    final label = (subject['label'] ?? '').toString();
    final msgs = <QueryMessage>[
      for (final m
          in (j['messages'] is List ? j['messages'] as List : const []))
        if (m is Map)
          QueryMessage(
            fromAccountant: m['role'] == 'accountant',
            author: (m['author'] ?? '').toString(),
            text: (m['text'] ?? '').toString(),
            at: DateTime.tryParse((m['ts'] ?? '').toString())?.toLocal(),
          ),
    ];
    return ClientQuery(
      id: id,
      about: label.isEmpty ? kind : '$kind: $label',
      open: j['status'] == 'open',
      waitingOnYou: j['waiting_on'] == 'client',
      messages: msgs,
    );
  }
}
