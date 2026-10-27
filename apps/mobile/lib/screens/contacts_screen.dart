import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/books.dart';
import '../services/phone_contacts.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/vat_status.dart';
import 'payments_sheets.dart';
import 'phone_import_sheet.dart';
import 'settings_screen.dart';

/// Contacts from `GET /contacts`: search the list, see each open balance,
/// and open a statement per contact. Money is worked out by the runtime.
class ContactsScreen extends StatefulWidget {
  const ContactsScreen({super.key, this.phoneContacts});

  /// The system contact picker; injectable so widget tests can mock it.
  final PhoneContacts? phoneContacts;

  @override
  State<ContactsScreen> createState() => _ContactsScreenState();
}

class _ContactsScreenState extends State<ContactsScreen> {
  final AuthService _auth = AuthService();
  final _search = TextEditingController();
  AppSettings? _settings;
  Account? _account;
  bool _authChecked = false;
  bool _loading = false;
  String? _error;
  List<Map<String, dynamic>> _rows = const [];
  String _query = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final settings = await AppSettings.load();
    Account? account;
    try {
      account = await _auth.account();
    } catch (_) {
      account = null;
    }
    if (!mounted) return;
    setState(() {
      _settings = settings;
      _account = account;
      _authChecked = true;
    });
    if (account != null) await _reload();
  }

  Future<void> _reload() async {
    final settings = _settings;
    if (settings == null || _account == null || _loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final client = await booksClient(settings, _auth, _account);
      final decoded = await client.contacts();
      final contacts = decoded['contacts'];
      if (!mounted) return;
      setState(() {
        _rows = [
          if (contacts is List)
            for (final c in contacts)
              if (c is Map) Map<String, dynamic>.from(c),
        ];
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Open the system contact picker, then review the picks before
  /// importing. The picker reads only the contacts the user taps (no
  /// Contacts permission); the review sheet saves them to the books.
  Future<void> _addFromPhone() async {
    final settings = _settings;
    if (settings == null || _account == null) return;
    final picker = widget.phoneContacts ?? PhoneContacts();
    PickedPhoneContact? first;
    try {
      first = await picker.pickContact();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(friendly(e))),
      );
      return;
    }
    if (first == null || !mounted) return;
    final imported = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => PhoneImportSheet(
        initialPicks: [first!],
        onPickAnother: picker.pickContact,
        onImport: (body) async {
          final client =
              await booksClient(settings, _auth, _account);
          return client.importPhoneContacts(body);
        },
      ),
    );
    if (imported == true) await _reload();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          'Contacts',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        actions: [
          if (_account != null) ...[
            IconButton(
              icon: const Icon(Icons.person_add_outlined),
              tooltip: 'Add from phone',
              constraints:
                  const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : _addFromPhone,
            ),
            IconButton(
              icon: const Icon(Icons.refresh_outlined),
              tooltip: 'Reload contacts',
              constraints:
                  const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : _reload,
            ),
          ],
        ],
      ),
      body: !_authChecked || _loading && _rows.isEmpty && _error == null
          ? const Center(child: CircularProgressIndicator())
          : _account == null
              ? _listView(_sampleContacts, sample: true)
              : _error != null && _rows.isEmpty
                  ? _errorView()
                  : _listView(_rows),
    );
  }

  Widget _errorView() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(_error ?? 'Could not load contacts.',
                textAlign: TextAlign.center),
            const SizedBox(height: 12),
            FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: AccnomosColors.teal,
                minimumSize: const Size.fromHeight(48),
              ),
              onPressed: _reload,
              child: const Text('Try again'),
            ),
          ],
        ),
      ),
    );
  }

  /// Fictional sample contacts for the signed-out demo. The VAT chips and
  /// the customer VRN mirror the live list; tapping one opens a local
  /// sample statement (nothing is saved).
  static const List<Map<String, dynamic>> _sampleContacts = [
    {
      'id': 'sample-brixton-timber',
      'kind': 'supplier',
      'name': 'Brixton Timber Co',
      'vat_status': 'registered',
      'vrn': 'GB 123 4567 89',
      'email': 'sales@brixton-timber.example',
      'totals': {'balance_pence': -48210},
    },
    {
      'id': 'sample-dave-oddjobs',
      'kind': 'supplier',
      'name': 'Dave Oddjobs',
      'vat_status': 'unknown',
      'email': 'dave@oddjobs.example',
      'totals': {'balance_pence': 0},
    },
    {
      'id': 'sample-camberwell-ceramics',
      'kind': 'supplier',
      'name': 'Camberwell Ceramics',
      'vat_status': 'not_registered',
      'email': 'hello@camberwell-ceramics.example',
      'totals': {'balance_pence': -1299},
    },
    {
      'id': 'sample-peckham-bakery',
      'kind': 'customer',
      'name': 'Peckham Bakery Ltd',
      'vrn': 'GB 440 1234 55',
      'email': 'orders@peckham-bakery.example',
      'totals': {'balance_pence': 21240},
    },
  ];

  List<Map<String, dynamic>> _filter(
      List<Map<String, dynamic>> rows) {
    final q = _query.trim().toLowerCase();
    if (q.isEmpty) return rows;
    return rows.where((c) {
      final name = (c['name'] ?? '').toString().toLowerCase();
      final email = (c['email'] ?? '').toString().toLowerCase();
      return name.contains(q) || email.contains(q);
    }).toList();
  }

  Widget _listView(List<Map<String, dynamic>> all, {bool sample = false}) {
    final rows = _filter(all);
    return Column(
      children: [
        if (sample)
          Container(
            width: double.infinity,
            margin: const EdgeInsets.fromLTRB(16, 4, 16, 0),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(12),
              border:
                  Border.all(color: const Color(0xFFE3E1D8)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'SAMPLE — FICTIONAL CONTACTS · demo data only',
                  style: TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 12,
                    color: AccnomosColors.muted,
                  ),
                ),
                const SizedBox(height: 8),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    style: FilledButton.styleFrom(
                      backgroundColor: AccnomosColors.teal,
                      minimumSize: const Size.fromHeight(48),
                    ),
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(
                          builder: (_) => const SettingsScreen()),
                    ).then((_) => _load()),
                    child: const Text('Sign in to see your contacts'),
                  ),
                ),
              ],
            ),
          ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
          child: TextField(
            controller: _search,
            decoration: const InputDecoration(
              hintText: 'Search name or email',
              prefixIcon: Icon(Icons.search_outlined),
              border: OutlineInputBorder(),
              filled: true,
              fillColor: Colors.white,
            ),
            onChanged: (value) => setState(() => _query = value),
          ),
        ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Text(_error!,
                style: const TextStyle(color: AccnomosColors.muted)),
          ),
        Expanded(
          child: rows.isEmpty
              ? const Center(child: Text('No contacts found.'))
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                  itemCount: rows.length,
                  separatorBuilder: (_, _) =>
                      const SizedBox(height: 8),
                  itemBuilder: (context, i) =>
                      _row(context, rows[i], sample: sample),
                ),
        ),
      ],
    );
  }

  Widget _row(BuildContext context, Map<String, dynamic> contact,
      {bool sample = false}) {
    final totals = contact['totals'];
    final balance = totals is Map
        ? ((totals['balance_pence'] ?? 0) as num)
        : 0;
    return Card(
      margin: EdgeInsets.zero,
      child: ListTile(
        minVerticalPadding: 10,
        title: Text(
          (contact['name'] ?? 'Unnamed').toString(),
          style: const TextStyle(fontWeight: FontWeight.w700),
        ),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(_kindLabel(contact),
                style:
                    const TextStyle(color: AccnomosColors.muted)),
            _vatLine(contact),
          ],
        ),
        trailing: Text(
          _balanceLabel(balance),
          style: TextStyle(
            fontWeight: FontWeight.w800,
            color: balance > 0
                ? AccnomosColors.tealDark
                : balance < 0
                    ? const Color(0xFF8A3F06)
                    : AccnomosColors.muted,
          ),
        ),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => ContactDetailScreen(
              contactId: (contact['id'] ?? '').toString(),
              name: (contact['name'] ?? 'Contact').toString(),
              settings: _settings!,
              auth: _auth,
              account: _account,
              contact: contact,
              sampleMode: sample,
            ),
          ),
        ),
      ),
    );
  }

  /// One line under the kind: suppliers get a VAT status chip (nothing when
  /// unknown), customers show their VAT number when the books know it.
  Widget _vatLine(Map<String, dynamic> contact) {
    final kind = (contact['kind'] ?? '').toString();
    if (kind == 'customer') {
      final vrn = (contact['vrn'] ?? '').toString().trim();
      if (vrn.isEmpty) return const SizedBox.shrink();
      return Padding(
        padding: const EdgeInsets.only(top: 2),
        child: Text(
          'VAT $vrn',
          style: const TextStyle(
            color: AccnomosColors.muted,
            fontSize: 12,
          ),
        ),
      );
    }
    final status = (contact['vat_status'] ?? 'unknown').toString();
    if (status != vatStatusRegistered &&
        status != vatStatusNotRegistered) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: VatStatusChip(status: status),
    );
  }

  static String _kindLabel(Map<String, dynamic> contact) {
    switch ((contact['kind'] ?? '').toString()) {
      case 'customer':
        return 'Customer';
      case 'supplier':
        return 'Supplier';
      case 'both':
        return 'Customer · Supplier';
      default:
        return 'Contact';
    }
  }

  /// Signed from your side: + they owe you, − you owe them.
  static String _balanceLabel(num pence) {
    if (pence > 0) return '${gbp(pence)} owed';
    if (pence < 0) return 'owe ${gbp(-pence)}';
    return 'Settled';
  }
}

/// One contact: VAT status and number, statement over a chosen range, and
/// unpaid aged balances. Signed in, everything comes from the runtime
/// (`GET /contacts`, `GET /contacts/{id}/statement`, `GET /contacts/aged`,
/// saving through `editContact`); signed out, [sampleMode] shows local
/// fictional lines and edits stay on the phone.
class ContactDetailScreen extends StatefulWidget {
  const ContactDetailScreen({
    super.key,
    required this.contactId,
    required this.name,
    required this.settings,
    required this.auth,
    required this.account,
    this.contact,
    this.sampleMode = false,
    this.focusVatStatus = false,
  });

  final String contactId;
  final String name;
  final AppSettings settings;
  final AuthService auth;
  final Account? account;

  /// The contact row when the list already has it (vat_status, vrn, kind).
  final Map<String, dynamic>? contact;

  /// Signed-out demo: local sample data, nothing is saved.
  final bool sampleMode;

  /// Put keyboard/screen-reader focus on the VAT status control (opened
  /// from a Review card asking "Is `supplier` VAT-registered?").
  final bool focusVatStatus;

  @override
  State<ContactDetailScreen> createState() => _ContactDetailState();
}

/// Statement range choices: the calendar quarter holding today, the one
/// before it, or a custom range from the date picker.
enum _Range { thisQuarter, lastQuarter, custom }

class _ContactDetailState extends State<ContactDetailScreen> {
  bool _loading = true;
  bool _statementLoading = false;
  String? _error;
  Map<String, dynamic>? _statement;
  Map<String, dynamic>? _contact;
  Map<String, dynamic>? _agedRow;
  String _vatStatus = vatStatusUnknown;
  bool _savingVat = false;
  final _vrn = TextEditingController();
  String? _vrnError;
  bool _savingVrn = false;
  final _terms = TextEditingController();
  String? _termsError;
  bool _savingTerms = false;
  _Range _range = _Range.thisQuarter;
  DateTimeRange? _custom;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void dispose() {
    _vrn.dispose();
    _terms.dispose();
    super.dispose();
  }

  /// Calendar quarter holding [day].
  static ({DateTime start, DateTime end}) _quarterOf(DateTime day) {
    final firstMonth = (day.month - 1) ~/ 3 * 3 + 1;
    return (
      start: DateTime(day.year, firstMonth, 1),
      end: DateTime(day.year, firstMonth + 3, 0),
    );
  }

  String? get _from {
    final now = DateTime.now();
    switch (_range) {
      case _Range.thisQuarter:
        return isoDate(_quarterOf(now).start);
      case _Range.lastQuarter:
        final before = _quarterOf(now).start
            .subtract(const Duration(days: 1));
        return isoDate(_quarterOf(before).start);
      case _Range.custom:
        final custom = _custom;
        return custom == null ? null : isoDate(custom.start);
    }
  }

  String? get _to {
    final now = DateTime.now();
    switch (_range) {
      case _Range.thisQuarter:
        return isoDate(_quarterOf(now).end);
      case _Range.lastQuarter:
        final before = _quarterOf(now).start
            .subtract(const Duration(days: 1));
        return isoDate(_quarterOf(before).end);
      case _Range.custom:
        final custom = _custom;
        return custom == null ? null : isoDate(custom.end);
    }
  }

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    if (widget.sampleMode) {
      final record = widget.contact ?? const {};
      setState(() {
        _contact = Map<String, dynamic>.from(record);
        _vatStatus =
            (record['vat_status'] ?? vatStatusUnknown).toString();
        _vrn.text = (record['vrn'] ?? '').toString();
        _terms.text = (record['terms_days'] ?? '').toString();
        _statement = _sampleStatement(record, _from, _to);
        _agedRow = _sampleAged(record);
        _loading = false;
      });
      return;
    }
    try {
      final client = await booksClient(
          widget.settings, widget.auth, widget.account);
      final decoded = await client.contactStatement(
        widget.contactId,
        from: _from,
        to: _to,
      );
      Map<String, dynamic>? record = widget.contact == null
          ? null
          : Map<String, dynamic>.from(widget.contact!);
      Map<String, dynamic>? agedRow;
      try {
        final contacts = await client.contacts();
        final list = contacts['contacts'];
        if (list is List) {
          for (final c in list) {
            if (c is Map &&
                (c['id'] ?? '').toString() == widget.contactId) {
              record = Map<String, dynamic>.from(c);
              break;
            }
          }
        }
        agedRow = _findAgedRow(
            await client.agedBalances(), widget.contactId);
      } catch (_) {
        // The statement is the core; the VAT record and aged balances
        // stay hidden when those calls fail.
      }
      if (!mounted) return;
      setState(() {
        _statement = decoded;
        _contact = record;
        _agedRow = agedRow;
        if (record != null) {
          _vatStatus =
              (record['vat_status'] ?? vatStatusUnknown).toString();
          _vrn.text = (record['vrn'] ?? '').toString();
          _terms.text = (record['terms_days'] ?? '').toString();
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _changeRange(_Range range) async {
    if (range == _Range.custom) {
      final picked = await showDateRangePicker(
        context: context,
        firstDate: DateTime(2000),
        lastDate: DateTime.now(),
        initialDateRange: _custom,
      );
      if (picked == null) return;
      setState(() {
        _custom = picked;
        _range = _Range.custom;
      });
    } else {
      setState(() => _range = range);
    }
    if (widget.sampleMode) {
      setState(() => _statement =
          _sampleStatement(widget.contact ?? const {}, _from, _to));
      return;
    }
    setState(() => _statementLoading = true);
    try {
      final client = await booksClient(
          widget.settings, widget.auth, widget.account);
      final decoded = await client.contactStatement(
        widget.contactId,
        from: _from,
        to: _to,
      );
      if (!mounted) return;
      setState(() => _statement = decoded);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(friendly(e))));
    } finally {
      if (mounted) setState(() => _statementLoading = false);
    }
  }

  Future<void> _saveVatStatus(String value) async {
    if (widget.sampleMode) {
      setState(() => _vatStatus = value);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Sample contact — sign in to save.')));
      }
      return;
    }
    setState(() => _savingVat = true);
    try {
      final client = await booksClient(
          widget.settings, widget.auth, widget.account);
      final updated =
          await client.editContact(widget.contactId, {'vat_status': value});
      if (!mounted) return;
      setState(() {
        _vatStatus =
            (updated['vat_status'] ?? value).toString();
        _contact = {...?_contact, ...updated};
      });
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('VAT status saved.')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(friendly(e))));
    } finally {
      if (mounted) setState(() => _savingVat = false);
    }
  }

  Future<void> _saveVrn() async {
    final text = _vrn.text.trim();
    if (text.isNotEmpty && !isValidContactVrn(text)) {
      setState(() => _vrnError =
          'Check the VAT number: GB followed by 9 or 12 digits '
          '(spaces are fine).');
      return;
    }
    if (widget.sampleMode) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Sample contact — sign in to save.')));
      }
      return;
    }
    setState(() => _savingVrn = true);
    try {
      final client = await booksClient(
          widget.settings, widget.auth, widget.account);
      final updated = await client.editContact(
          widget.contactId, {'vrn': text.isEmpty ? null : text});
      if (!mounted) return;
      setState(() {
        _contact = {...?_contact, ...updated};
        _vrn.text = (updated['vrn'] ?? '').toString();
      });
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('VAT number saved.')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(friendly(e))));
    } finally {
      if (mounted) setState(() => _savingVrn = false);
    }
  }

  /// Payment terms in days (blank = the 30-day default, 0–365 like the web).
  Future<void> _saveTerms() async {
    final text = _terms.text.trim();
    int? days;
    if (text.isNotEmpty) {
      days = int.tryParse(text);
      if (days == null || days < 0 || days > 365) {
        setState(() => _termsError =
            'Payment terms are a whole number of days, 0 to 365 (blank for the usual 30).');
        return;
      }
    }
    setState(() => _termsError = null);
    if (widget.sampleMode) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Sample contact — sign in to save.')));
      }
      return;
    }
    setState(() => _savingTerms = true);
    try {
      final client = await booksClient(
          widget.settings, widget.auth, widget.account);
      final updated = await client.editContact(
          widget.contactId, {'terms_days': days});
      if (!mounted) return;
      setState(() {
        _contact = {...?_contact, ...updated};
        _terms.text = (updated['terms_days'] ?? '').toString();
      });
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Payment terms saved.')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(friendly(e))));
    } finally {
      if (mounted) setState(() => _savingTerms = false);
    }
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  List<Map<String, dynamic>> _credits() {
    final statement = _statement ?? const {};
    final raw = statement['credits'];
    if (raw is! List) return const [];
    return [
      for (final c in raw)
        if (c is Map) Map<String, dynamic>.from(c),
    ];
  }

  List<Map<String, dynamic>> _openDocs() {
    final statement = _statement ?? const {};
    final raw = statement['open_documents'];
    if (raw is! List) return const [];
    return [
      for (final d in raw)
        if (d is Map) Map<String, dynamic>.from(d),
    ];
  }

  List<Map<String, dynamic>> _creditUses() {
    final statement = _statement ?? const {};
    final raw = statement['credit_uses'];
    if (raw is! List) return const [];
    return [
      for (final u in raw)
        if (u is Map) Map<String, dynamic>.from(u),
    ];
  }

  /// Apply-credit sheet → confirm sheet → runtime → refresh.
  Future<void> _applyCredit() async {
    final credits = _credits();
    final docs = _openDocs();
    if (credits.isEmpty) return;
    final used = await showApplyCreditSheet(
      context: context,
      contactName: widget.name,
      credits: credits,
      documents: docs,
      apply: (
          {required credit,
          required eventId,
          amountPence,
          date}) async {
        final client = await booksClient(
            widget.settings, widget.auth, widget.account);
        return client.applyCredit(
          credit: credit,
          eventId: eventId,
          amountPence: amountPence,
          date: date,
        );
      },
    );
    if (used != null && mounted) {
      _snack("Credit applied for ${widget.name}.");
      await _reload();
    }
  }

  /// Refund sheet → confirm sheet → runtime → refresh.
  Future<void> _refundCredit() async {
    final credits = _credits();
    if (credits.isEmpty) return;
    final used = await showRefundSheet(
      context: context,
      contactName: widget.name,
      credits: credits,
      refund: (
          {required credit,
          required amountPence,
          required date,
          required account,
          reference}) async {
        final client = await booksClient(
            widget.settings, widget.auth, widget.account);
        return client.refundCredit(
          credit: credit,
          amountPence: amountPence,
          date: date,
          account: account,
          reference: reference,
        );
      },
    );
    if (used != null && mounted) {
      _snack('Refund recorded for ${widget.name}.');
      await _reload();
    }
  }

  /// Confirm first, then take a credit apply or refund back.
  Future<void> _removeCreditUse(Map<String, dynamic> use) async {
    final id = (use['id'] ?? '').toString();
    final kind = (use['kind'] ?? '').toString();
    final what = kind == 'refund'
        ? 'Refund'
        : 'Credit applied to ${(use['reference'] ?? 'a document').toString()}';
    final confirmed = await showConfirmSheet(
      context: context,
      title: kind == 'refund'
          ? 'Take back this refund?'
          : 'Take back this applied credit?',
      figures: [
        ConfirmFigure('What', what),
        ConfirmFigure('Date', ukDate((use['date'] ?? '').toString())),
        ConfirmFigure(
            'Amount', gbp((use['amount_pence'] ?? 0) as num)),
      ],
      confirmLabel: 'Remove',
      action: () async {
        final client = await booksClient(
            widget.settings, widget.auth, widget.account);
        await client.removeCreditUse(id);
      },
    );
    if (confirmed && mounted) {
      _snack('Credit use removed for ${widget.name}.');
      await _reload();
    }
  }

  /// Bill-payment sheet → confirm sheet → runtime → refresh.
  Future<void> _payBill(Map<String, dynamic> bill) async {
    final recorded = await showRecordBillPaymentSheet(
      context: context,
      openDoc: bill,
      record: (body) async {
        final client = await booksClient(
            widget.settings, widget.auth, widget.account);
        return client.recordPayment(body);
      },
    );
    if (recorded != null && mounted) {
      _snack('Payment recorded for ${widget.name}.');
      await _reload();
    }
  }

  /// Confirm first, then remove a statement payment or refund line.
  Future<void> _removeStatementLine(Map<String, dynamic> line) async {
    final paymentId = (line['payment_id'] ?? '').toString();
    if (paymentId.isEmpty) return;
    final isRefund = (line['kind'] ?? '').toString() == 'refund';
    final confirmed = await showConfirmSheet(
      context: context,
      title: isRefund ? 'Take back this refund?' : 'Remove this payment?',
      figures: [
        ConfirmFigure('What', (line['details'] ?? '—').toString()),
        ConfirmFigure('Date', ukDate((line['date'] ?? '').toString())),
        ConfirmFigure(
            'Amount', gbp((line['amount_pence'] ?? 0) as num)),
      ],
      confirmLabel: 'Remove',
      action: () async {
        final client = await booksClient(
            widget.settings, widget.auth, widget.account);
        if (isRefund) {
          await client.removeCreditUse(paymentId);
        } else {
          await client.removePayment(paymentId);
        }
      },
    );
    if (confirmed && mounted) {
      _snack(isRefund
          ? 'Refund removed for ${widget.name}.'
          : 'Payment removed for ${widget.name}.');
      await _reload();
    }
  }

  static Map<String, dynamic>? _findAgedRow(
      Map<String, dynamic> aged, String id) {
    for (final table in [aged['debtors'], aged['creditors']]) {
      if (table is Map && table['rows'] is List) {
        for (final row in table['rows'] as List) {
          if (row is Map &&
              (row['contact_id'] ?? '').toString() == id) {
            return Map<String, dynamic>.from(row);
          }
        }
      }
    }
    return null;
  }

  static int _lineNet(Map<String, dynamic> line) =>
      ((line['amount_pence'] ?? 0) as num).toInt() +
      ((line['paid_pence'] ?? 0) as num).toInt();

  /// Fictional statement for the signed-out demo, running balances worked
  /// out from the visible lines like the runtime does.
  static Map<String, dynamic> _sampleStatement(
      Map<String, dynamic> record, String? from, String? to) {
    final totals = record['totals'];
    final balance = totals is Map
        ? ((totals['balance_pence'] ?? 0) as num).toInt()
        : 0;
    final customer = (record['kind'] ?? '').toString() == 'customer';
    final all = [
      if (balance != 0)
        {
          'date': '2026-10-09',
          'details': customer ? 'Sales invoice' : 'Purchase on account',
          'reference': 'INV-2041',
          'amount_pence': balance,
          'paid_pence': 0,
          'balance_pence': balance,
        },
      {
        'date': '2026-10-16',
        'details': customer
            ? 'Sales invoice, paid at the time'
            : 'Purchase, paid at the time',
        'reference': 'TILL-114',
        'amount_pence': customer ? 3600 : -3600,
        'paid_pence': customer ? -3600 : 3600,
        'balance_pence': balance,
      },
    ];
    var running = 0;
    for (final line in all) {
      if (from != null &&
          line['date'].toString().compareTo(from) < 0) {
        running += _lineNet(line);
      }
    }
    final opening = running;
    final shown = <Map<String, dynamic>>[];
    for (final line in all) {
      if (from != null &&
          line['date'].toString().compareTo(from) < 0) {
        continue;
      }
      if (to != null && line['date'].toString().compareTo(to) > 0) {
        continue;
      }
      running += _lineNet(line);
      shown.add({...line, 'balance_pence': running});
    }
    return {
      'start': from,
      'end': to,
      'opening_balance_pence': opening,
      'closing_balance_pence': running,
      'lines': shown,
    };
  }

  /// Fictional aged row for the signed-out demo.
  static Map<String, dynamic> _sampleAged(
      Map<String, dynamic> record) {
    final totals = record['totals'];
    final total = totals is Map
        ? (((totals['balance_pence'] ?? 0) as num).abs()).toInt()
        : 0;
    final recent = (total * 0.7).round();
    return {
      'contact_id': (record['id'] ?? '').toString(),
      'buckets': {
        '0-30': recent,
        '31-60': total - recent,
        '61-90': 0,
        '90+': 0,
      },
      'total_pence': total,
    };
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          widget.name,
          style: Theme.of(context).textTheme.titleMedium,
        ),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(_error!,
                            textAlign: TextAlign.center),
                        const SizedBox(height: 12),
                        FilledButton(
                          style: FilledButton.styleFrom(
                            backgroundColor: AccnomosColors.teal,
                            minimumSize:
                                const Size.fromHeight(48),
                          ),
                          onPressed: _reload,
                          child: const Text('Try again'),
                        ),
                      ],
                    ),
                  ),
                )
              : _statementView(),
    );
  }

  Widget _statementView() {
    final statement = _statement ?? const {};
    final lines = statement['lines'];
    final rows = [
      if (lines is List)
        for (final l in lines)
          if (l is Map) Map<String, dynamic>.from(l),
    ];
    final opening =
        (statement['opening_balance_pence'] ?? 0) as num;
    final closing =
        (statement['closing_balance_pence'] ?? 0) as num;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _vatCard(),
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(16),
            border:
                Border.all(color: const Color(0xFFE3E1D8)),
          ),
          child: Column(
            children: [
              _balanceRow('Opening', opening),
              const SizedBox(height: 6),
              _balanceRow('Balance now', closing,
                  bold: true),
            ],
          ),
        ),
        const SizedBox(height: 12),
        _creditCard(),
        _billsCard(),
        _rangePicker(),
        if (_statementLoading)
          const Padding(
            padding: EdgeInsets.only(top: 12),
            child: Center(child: CircularProgressIndicator()),
          )
        else if (rows.isEmpty)
          const Padding(
            padding: EdgeInsets.only(top: 4),
            child: Text(
              'No statement lines yet.',
              style: TextStyle(color: AccnomosColors.muted),
            ),
          )
        else
          for (final line in rows) _lineCard(line),
        const SizedBox(height: 12),
        _agedCard(),
        const SizedBox(height: 12),
        _termsCard(),
      ],
    );
  }

  /// VAT status and number. The segmented control shows only for contacts
  /// the user buys from (like the web); the VAT number is editable for all.
  Widget _vatCard() {
    final record = _contact;
    if (record == null) return const SizedBox.shrink();
    final buysFrom = (record['kind'] ?? '').toString() != 'customer';
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
            'VAT',
            style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
          ),
          const SizedBox(height: 8),
          if (buysFrom) ...[
            VatStatusSegmented(
              value: _vatStatus,
              autofocus: widget.focusVatStatus,
              enabled: !_savingVat,
              onChanged: _saveVatStatus,
            ),
            if (_savingVat)
              const Padding(
                padding: EdgeInsets.only(top: 4),
                child: Text(
                  'Saving…',
                  style: TextStyle(
                    color: AccnomosColors.muted,
                    fontSize: 12,
                  ),
                ),
              ),
            const SizedBox(height: 4),
            const Text(
              'Over £250 with no VAT number, Accnomos asks about unknown '
              'suppliers; this setting answers it for good.',
              style: TextStyle(
                color: AccnomosColors.muted,
                fontSize: 13,
              ),
            ),
            const SizedBox(height: 12),
          ],
          TextField(
            controller: _vrn,
            decoration: InputDecoration(
              labelText: 'VAT number',
              hintText: 'GB 123 4567 89',
              helperText: 'GB followed by 9 or 12 digits; spaces are '
                  'fine. Leave blank if they have none.',
              helperMaxLines: 2,
              errorText: _vrnError,
              border: const OutlineInputBorder(),
              filled: true,
              fillColor: Colors.white,
            ),
            textCapitalization: TextCapitalization.characters,
            onChanged: (_) {
              if (_vrnError != null) {
                setState(() => _vrnError = null);
              }
            },
          ),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
              style: OutlinedButton.styleFrom(
                minimumSize: const Size.fromHeight(48),
              ),
              onPressed: _savingVrn ? null : _saveVrn,
              child: Text(
                  _savingVrn ? 'Saving…' : 'Save VAT number'),
            ),
          ),
          if (widget.sampleMode)
            const Padding(
              padding: EdgeInsets.only(top: 4),
              child: Text(
                'Sample — sign in to save changes.',
                style: TextStyle(
                  color: AccnomosColors.muted,
                  fontSize: 12,
                ),
              ),
            ),
        ],
      ),
    );
  }

  /// Payment terms in days, like the web Edit. Blank is the 30-day default.
  Widget _termsCard() {
    final record = _contact;
    if (record == null) return const SizedBox.shrink();
    final current = (record['terms_days'] ?? '').toString();
    final showing = current.isEmpty ? '30 days (the usual)' : '$current days';
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
            'Payment terms',
            style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
          ),
          const SizedBox(height: 4),
          Text(
            'Now: $showing. Due dates fall back to this when an invoice has none.',
            style: const TextStyle(
              color: AccnomosColors.muted,
              fontSize: 13,
            ),
          ),
          const SizedBox(height: 8),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: TextField(
                  controller: _terms,
                  keyboardType: TextInputType.number,
                  decoration: InputDecoration(
                    labelText: 'Payment terms (days)',
                    hintText: 'Blank for 30',
                    errorText: _termsError,
                    border: const OutlineInputBorder(),
                    filled: true,
                    fillColor: Colors.white,
                  ),
                  onChanged: (_) {
                    if (_termsError != null) {
                      setState(() => _termsError = null);
                    }
                  },
                ),
              ),
              const SizedBox(width: 8),
              FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size(48, 56),
                ),
                onPressed: _savingTerms ? null : _saveTerms,
                child: Text(_savingTerms ? '…' : 'Save'),
              ),
            ],
          ),
          if (widget.sampleMode)
            const Padding(
              padding: EdgeInsets.only(top: 4),
              child: Text(
                'Sample — sign in to save changes.',
                style: TextStyle(
                  color: AccnomosColors.muted,
                  fontSize: 12,
                ),
              ),
            ),
        ],
      ),
    );
  }

  /// Credit on account from the runtime statement, with Apply credit and
  /// Refund plus the uses so far (each with Remove). Hidden when there is
  /// no credit and no uses.
  Widget _creditCard() {
    final statement = _statement ?? const {};
    final creditPence = (statement['credit_pence'] ?? 0) as num;
    final credits = _credits();
    final uses = _creditUses();
    if (creditPence == 0 && credits.isEmpty && uses.isEmpty) {
      return const SizedBox.shrink();
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
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
                'Credit on account',
                style:
                    TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
              ),
              const SizedBox(height: 4),
              Text(
                gbp(creditPence),
                style: const TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: 20,
                ),
              ),
              if (!widget.sampleMode && credits.isNotEmpty) ...[
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    OutlinedButton(
                      style: OutlinedButton.styleFrom(
                        minimumSize: const Size(48, 48),
                      ),
                      onPressed: _applyCredit,
                      child: const Text('Apply credit'),
                    ),
                    OutlinedButton(
                      style: OutlinedButton.styleFrom(
                        minimumSize: const Size(48, 48),
                      ),
                      onPressed: _refundCredit,
                      child: const Text('Refund'),
                    ),
                  ],
                ),
              ],
              if (uses.isNotEmpty) ...[
                const SizedBox(height: 8),
                for (final use in uses) _creditUseRow(use),
              ],
            ],
          ),
        ),
        const SizedBox(height: 12),
      ],
    );
  }

  Widget _creditUseRow(Map<String, dynamic> use) {
    final kind = (use['kind'] ?? '').toString();
    final what = kind == 'refund'
        ? 'Refund'
        : 'Credit applied to ${(use['reference'] ?? 'a document').toString()}';
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(what),
                Text(
                  '${ukDate((use['date'] ?? '').toString())} · '
                  '${gbp((use['amount_pence'] ?? 0) as num)}',
                  style: const TextStyle(
                      color: AccnomosColors.muted, fontSize: 12),
                ),
              ],
            ),
          ),
          if (!widget.sampleMode)
            TextButton(
              onPressed: () => _removeCreditUse(use),
              style: TextButton.styleFrom(
                minimumSize: const Size(48, 48),
              ),
              child: const Text('Remove'),
            ),
        ],
      ),
    );
  }

  /// Bills to pay: open purchase documents from the runtime statement, each
  /// with Record payment. Hidden when none are open.
  Widget _billsCard() {
    final bills = [
      for (final doc in _openDocs())
        if ((doc['side'] ?? '').toString() == 'purchase' &&
            ((doc['outstanding_pence'] ?? 0) as num) > 0)
          doc,
    ];
    if (bills.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
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
                'Bills to pay',
                style:
                    TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
              ),
              const SizedBox(height: 8),
              for (final bill in bills) _billRow(bill),
            ],
          ),
        ),
        const SizedBox(height: 12),
      ],
    );
  }

  Widget _billRow(Map<String, dynamic> bill) {
    final reference =
        (bill['reference'] ?? 'Bill').toString();
    final owed = gbp((bill['outstanding_pence'] ?? 0) as num);
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  reference,
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                Text(
                  'Due ${ukDate((bill['due_date'] ?? '').toString())} · '
                  '$owed left',
                  style: const TextStyle(
                      color: AccnomosColors.muted, fontSize: 12),
                ),
              ],
            ),
          ),
          if (!widget.sampleMode)
            TextButton(
              onPressed: () => _payBill(bill),
              style: TextButton.styleFrom(
                minimumSize: const Size(48, 48),
              ),
              child: const Text('Record payment'),
            ),
        ],
      ),
    );
  }

  Widget _rangePicker() {
    final statement = _statement ?? const {};
    final start = (statement['start'] ?? '').toString();
    final end = (statement['end'] ?? '').toString();
    final showing = start.isNotEmpty && end.isNotEmpty
        ? 'Showing ${ukDate(start)} – ${ukDate(end)}'
        : 'Everything so far';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            ChoiceChip(
              label: const Text('This quarter'),
              selected: _range == _Range.thisQuarter,
              onSelected: (_) => _changeRange(_Range.thisQuarter),
            ),
            ChoiceChip(
              label: const Text('Last quarter'),
              selected: _range == _Range.lastQuarter,
              onSelected: (_) => _changeRange(_Range.lastQuarter),
            ),
            ChoiceChip(
              label: const Text('Custom'),
              selected: _range == _Range.custom,
              onSelected: (_) => _changeRange(_Range.custom),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Text(
          showing,
          style: const TextStyle(
            color: AccnomosColors.muted,
            fontSize: 12,
          ),
        ),
        const SizedBox(height: 8),
      ],
    );
  }

  /// What is still owed, by days past the due date (not due / 0–30 / 31–60 /
  /// 61–90 / 90+) from `GET /contacts/aged`.
  Widget _agedCard() {
    final row = _agedRow;
    if (row == null) return const SizedBox.shrink();
    final buckets =
        row['buckets'] is Map ? Map.of(row['buckets'] as Map) : {};
    final total = (row['total_pence'] ?? 0) as num;
    const order = ['current', '0-30', '31-60', '61-90', '90+'];
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
            'Unpaid by age',
            style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
          ),
          const SizedBox(height: 8),
          if (total == 0)
            const Text(
              'Nothing unpaid.',
              style: TextStyle(color: AccnomosColors.muted),
            )
          else
            for (final bucket in order)
              _agedBar(
                bucket,
                (buckets[bucket] ?? 0) as num,
                total,
              ),
        ],
      ),
    );
  }

  Widget _agedBar(String bucket, num value, num total) {
    final Color fill;
    switch (bucket) {
      case '90+':
        fill = const Color(0xFFB45309);
      case '61-90':
        fill = AccnomosColors.teal;
      case '31-60':
        fill = const Color(0xFF3D9A8E);
      default:
        fill = const Color(0xFF9CCFC6);
    }
    final fraction =
        total > 0 ? (value / total).clamp(0.0, 1.0).toDouble() : 0.0;
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          SizedBox(
            width: 52,
            child: Text(
              bucket == 'current' ? 'not due' : bucket,
              style: const TextStyle(
                color: AccnomosColors.muted,
                fontSize: 12,
              ),
            ),
          ),
          Expanded(
            child: Container(
              height: 8,
              decoration: BoxDecoration(
                color: AccnomosColors.ground,
                borderRadius: BorderRadius.circular(999),
              ),
              child: Align(
                alignment: Alignment.centerLeft,
                child: FractionallySizedBox(
                  widthFactor: fraction,
                  child: Container(
                    decoration: BoxDecoration(
                      color: fill,
                      borderRadius: BorderRadius.circular(999),
                    ),
                  ),
                ),
              ),
            ),
          ),
          SizedBox(
            width: 76,
            child: Text(
              gbp(value),
              textAlign: TextAlign.right,
              style: const TextStyle(fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }

  Widget _balanceRow(String label, num pence, {bool bold = false}) {
    final style = TextStyle(
      fontWeight: bold ? FontWeight.w800 : FontWeight.w600,
      fontSize: bold ? 16 : 14,
    );
    return Row(
      children: [
        Expanded(child: Text(label, style: style)),
        Text(gbp(pence), style: style),
      ],
    );
  }

  Widget _lineCard(Map<String, dynamic> line) {
    final amount = (line['amount_pence'] ?? 0) as num;
    final balance = (line['balance_pence'] ?? 0) as num;
    final kind = (line['kind'] ?? '').toString();
    final removable = !widget.sampleMode &&
        (kind == 'payment' || kind == 'refund') &&
        (line['payment_id'] ?? '').toString().isNotEmpty;
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        minVerticalPadding: 10,
        title: Text(
          (line['details'] ?? '—').toString(),
          style: const TextStyle(fontWeight: FontWeight.w700),
        ),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              '${ukDate((line['date'] ?? '').toString())}'
              '${(line['reference'] ?? '').toString().isNotEmpty ? ' · ${(line['reference'] ?? '').toString()}' : ''}',
              style: const TextStyle(color: AccnomosColors.muted),
            ),
            if (removable)
              TextButton(
                onPressed: () => _removeStatementLine(line),
                style: TextButton.styleFrom(
                  minimumSize: const Size(48, 36),
                  padding: EdgeInsets.zero,
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
                child: const Text('Remove'),
              ),
          ],
        ),
        trailing: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text(gbp(amount),
                style: const TextStyle(
                    fontWeight: FontWeight.w800)),
            Text(gbp(balance),
                style: const TextStyle(
                    color: AccnomosColors.muted,
                    fontSize: 12)),
          ],
        ),
      ),
    );
  }
}
