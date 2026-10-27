import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/books.dart';
import '../services/settings.dart';
import '../theme.dart';
import 'invoice_send.dart';
import 'new_invoice_screen.dart';
import 'payments_sheets.dart';
import 'settings_screen.dart';

const _statuses = ['all', 'draft', 'sent', 'paid', 'void'];

/// Invoices from `GET /invoices`, filtered by status. Totals come from the
/// runtime; starting an invoice lives under "New invoice".
class InvoicesScreen extends StatefulWidget {
  const InvoicesScreen({super.key});

  @override
  State<InvoicesScreen> createState() => _InvoicesScreenState();
}

class _InvoicesScreenState extends State<InvoicesScreen> {
  final AuthService _auth = AuthService();
  AppSettings? _settings;
  Account? _account;
  bool _authChecked = false;
  bool _loading = false;
  String? _error;
  String _status = 'all';
  List<Map<String, dynamic>> _rows = const [];

  @override
  void initState() {
    super.initState();
    _load();
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
      final rows = await client.invoices(
          status: _status == 'all' ? null : _status);
      if (!mounted) return;
      setState(() => _rows = rows);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _pickStatus(String status) {
    if (status == _status) return;
    setState(() {
      _status = status;
      _rows = const [];
    });
    _reload();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          'Invoices',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        actions: [
          if (_account != null)
            IconButton(
              icon: const Icon(Icons.refresh_outlined),
              tooltip: 'Reload invoices',
              constraints:
                  const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : _reload,
            ),
        ],
      ),
      floatingActionButton: _account == null
          ? null
          : FloatingActionButton.extended(
              backgroundColor: AccnomosColors.teal,
              icon: const Icon(Icons.add_outlined),
              label: const Text('New invoice'),
              onPressed: () => Navigator.of(context)
                  .push(
                    MaterialPageRoute(
                        builder: (_) => NewInvoiceScreen(
                              settings: _settings!,
                              auth: _auth,
                              account: _account,
                            )),
                  )
                  .then((sent) {
                if (sent == true) _reload();
              }),
            ),
      body: !_authChecked || _loading && _rows.isEmpty && _error == null
          ? const Center(child: CircularProgressIndicator())
          : _account == null
              ? _signedOut()
              : Column(
                  children: [
                    _statusBar(),
                    if (_error != null)
                      Padding(
                        padding:
                            const EdgeInsets.fromLTRB(16, 0, 16, 8),
                        child: Text(_error!,
                            style: const TextStyle(
                                color: AccnomosColors.muted)),
                      ),
                    Expanded(
                      child: _rows.isEmpty && !_loading
                          ? const Center(
                              child:
                                  Text('No invoices here yet.'))
                          : _listView(),
                    ),
                  ],
                ),
    );
  }

  Widget _signedOut() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'Sign in to see your invoices.',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 12),
            FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: AccnomosColors.teal,
                minimumSize: const Size.fromHeight(48),
              ),
              onPressed: () => Navigator.of(context)
                  .push(
                    MaterialPageRoute(
                        builder: (_) =>
                            const SettingsScreen()),
                  )
                  .then((_) => _load()),
              child: const Text('Sign in'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _statusBar() {
    return SizedBox(
      height: 48,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        itemCount: _statuses.length,
        separatorBuilder: (_, _) =>
            const SizedBox(width: 8),
        itemBuilder: (context, i) {
          final s = _statuses[i];
          final selected = s == _status;
          return ChoiceChip(
            label: Text(_statusLabel(s)),
            selected: selected,
            onSelected: (_) => _pickStatus(s),
          );
        },
      ),
    );
  }

  Widget _listView() {
    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView.separated(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 88),
        itemCount: _rows.length,
        separatorBuilder: (_, _) =>
            const SizedBox(height: 8),
        itemBuilder: (context, i) =>
            _row(context, _rows[i]),
      ),
    );
  }

  Widget _row(BuildContext context, Map<String, dynamic> inv) {
    final customer = inv['customer'];
    final name = customer is Map
        ? (customer['name'] ?? '').toString()
        : '';
    final total = (inv['total_pence'] ?? 0) as num;
    final status = (inv['status'] ?? '').toString();
    return Card(
      margin: EdgeInsets.zero,
      child: ListTile(
        minVerticalPadding: 10,
        title: Text(
          '${(inv['number'] ?? '').toString()} · $name',
          style: const TextStyle(fontWeight: FontWeight.w700),
        ),
        subtitle: Text(
          '${_statusLabel(status)} · due ${ukDate((inv['due_date'] ?? '').toString())}',
          style:
              const TextStyle(color: AccnomosColors.muted),
        ),
        trailing: Text(
          gbp(total),
          style: const TextStyle(
              fontWeight: FontWeight.w800, fontSize: 15),
        ),
        onTap: () => Navigator.of(context)
            .push(
              MaterialPageRoute(
                builder: (_) => InvoiceDetailScreen(
                  number: (inv['number'] ?? '').toString(),
                  settings: _settings!,
                  auth: _auth,
                  account: _account,
                ),
              ),
            )
            .then((_) => _reload()),
      ),
    );
  }

  static String _statusLabel(String status) {
    switch (status) {
      case 'all':
        return 'All';
      case 'draft':
        return 'Draft';
      case 'sent':
        return 'Sent';
      case 'paid':
        return 'Paid';
      case 'void':
        return 'Void';
      default:
        return status;
    }
  }
}

/// One invoice: lines, totals from the runtime, and Send for drafts.
class InvoiceDetailScreen extends StatefulWidget {
  const InvoiceDetailScreen({
    super.key,
    required this.number,
    required this.settings,
    required this.auth,
    required this.account,
  });

  final String number;
  final AppSettings settings;
  final AuthService auth;
  final Account? account;

  @override
  State<InvoiceDetailScreen> createState() =>
      _InvoiceDetailState();
}

class _InvoiceDetailState extends State<InvoiceDetailScreen> {
  bool _loading = true;
  String? _error;
  Map<String, dynamic>? _invoice;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final client = await booksClient(
          widget.settings, widget.auth, widget.account);
      final decoded =
          await client.invoice(widget.number);
      if (!mounted) return;
      setState(() => _invoice = decoded);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _send() async {
    final sent = await confirmAndSend(
      context,
      settings: widget.settings,
      auth: widget.auth,
      account: widget.account,
      number: widget.number,
    );
    if (sent != null && mounted) {
      setState(() => _invoice = sent);
    }
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  /// Record payment sheet → confirm sheet → runtime → refresh.
  Future<void> _recordPayment(num balance) async {
    final recorded = await showRecordPaymentSheet(
      context: context,
      invoiceNumber: widget.number,
      balancePence: balance,
      record: ({required amountPence,
          required paidOn,
          required account,
          paymentRef}) async {
        final client = await booksClient(
            widget.settings, widget.auth, widget.account);
        return client.recordInvoicePayment(
          widget.number,
          amountPence: amountPence,
          paidOn: paidOn,
          account: account,
          paymentRef: paymentRef,
        );
      },
    );
    if (recorded != null && mounted) {
      _snack('Payment recorded on ${widget.number}.');
      await _reload();
    }
  }

  /// Confirm first, then remove the payment and refresh.
  Future<void> _removePayment(Map<String, dynamic> payment) async {
    final id = (payment['id'] ?? '').toString();
    final description =
        (payment['description'] ?? 'payment').toString();
    final confirmed = await showConfirmSheet(
      context: context,
      title: 'Remove this payment?',
      figures: [
        ConfirmFigure(
            'Date', ukDate((payment['date'] ?? '').toString())),
        ConfirmFigure('What', description),
        ConfirmFigure('Amount',
            gbp((payment['applied_pence'] ?? 0) as num)),
      ],
      confirmLabel: 'Remove',
      action: () async {
        final client = await booksClient(
            widget.settings, widget.auth, widget.account);
        await client.removeInvoicePayment(widget.number, id);
      },
    );
    if (confirmed && mounted) {
      _snack('Payment removed from ${widget.number}.');
      await _reload();
    }
  }

  /// Credit-note sheet → confirm sheet → runtime → refresh, naming the CN.
  Future<void> _createCreditNote(
      List<Map<String, dynamic>> lines) async {
    final created = await showCreateCreditNoteSheet(
      context: context,
      invoiceNumber: widget.number,
      lines: lines,
      create: (
          {required reason,
          issueDate,
          creditLines}) async {
        final client = await booksClient(
            widget.settings, widget.auth, widget.account);
        return client.createCreditNote(
          widget.number,
          reason: reason,
          issueDate: issueDate,
          lines: creditLines,
        );
      },
    );
    if (created != null && mounted) {
      final cn = (created['number'] ?? '').toString();
      _snack(cn.isEmpty
          ? 'Credit note created.'
          : 'Credit note $cn created.');
      await _reload();
    }
  }

  /// Void with a reason; the runtime refuses while payments, a matched line
  /// or issued credit notes stand, and its sentence shows in the sheet.
  Future<void> _voidInvoice(num total, num paid, num credited) async {
    final reason = TextEditingController();
    final typed = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Void this invoice?'),
        content: TextField(
          controller: reason,
          decoration: const InputDecoration(
            labelText: 'Reason',
            hintText: 'e.g. raised by mistake',
            border: OutlineInputBorder(),
          ),
          maxLength: 300,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: AccnomosColors.teal,
            ),
            onPressed: () =>
                Navigator.of(dialogContext).pop(reason.text.trim()),
            child: const Text('Continue'),
          ),
        ],
      ),
    );
    reason.dispose();
    if (typed == null || typed.isEmpty || !mounted) return;
    final confirmed = await showConfirmSheet(
      // ignore: use_build_context_synchronously
      context: context,
      title: 'Void ${widget.number}?',
      figures: [
        ConfirmFigure('Total', gbp(total)),
        ConfirmFigure('Paid', gbp(paid)),
        ConfirmFigure('Credited', gbp(credited)),
        ConfirmFigure('Reason', typed),
      ],
      confirmLabel: 'Void invoice',
      action: () async {
        final client = await booksClient(
            widget.settings, widget.auth, widget.account);
        final updated =
            await client.voidInvoice(widget.number, typed);
        if (mounted) setState(() => _invoice = updated);
      },
    );
    if (confirmed && mounted) {
      _snack('${widget.number} voided.');
      await _reload();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          widget.number,
          style: Theme.of(context).textTheme.titleMedium,
        ),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(_error!,
                        textAlign: TextAlign.center),
                  ),
                )
              : _detailView(),
    );
  }

  Widget _detailView() {
    final inv = _invoice ?? const {};
    final lines = inv['lines'];
    final rows = [
      if (lines is List)
        for (final l in lines)
          if (l is Map) Map<String, dynamic>.from(l),
    ];
    final status = (inv['status'] ?? '').toString();
    final customer = inv['customer'];
    final name =
        customer is Map ? (customer['name'] ?? '').toString() : '';
    // Payments and credit notes, worked out by the runtime (null for drafts
    // and void invoices, and from runtimes before part payments).
    final money = inv['money'];
    final paid = money is Map ? (money['paid_pence'] ?? 0) as num : null;
    final credited =
        money is Map ? (money['credited_pence'] ?? 0) as num : null;
    final balance =
        money is Map ? (money['balance_pence'] ?? 0) as num : null;
    final payments = [
      if (money is Map && money['payments'] is List)
        for (final p in money['payments'] as List)
          if (p is Map) Map<String, dynamic>.from(p),
    ];
    final creditNotes = [
      if (money is Map && money['credit_notes'] is List)
        for (final c in money['credit_notes'] as List)
          if (c is Map) Map<String, dynamic>.from(c),
    ];
    final total = (inv['total_pence'] ?? 0) as num;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(16),
            border:
                Border.all(color: const Color(0xFFE3E1D8)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(name,
                  style: Theme.of(context)
                      .textTheme
                      .titleMedium),
              const SizedBox(height: 2),
              Text(
                'Status: $status'
                '${(inv['sent_to'] ?? '').toString().isNotEmpty ? ' · sent to ${inv['sent_to']}' : ''}',
                style: const TextStyle(
                    color: AccnomosColors.muted),
              ),
              const Divider(height: 24),
              _totalRow('Net', (inv['net_pence'] ?? 0) as num),
              const SizedBox(height: 4),
              _totalRow('VAT', (inv['vat_pence'] ?? 0) as num),
              const SizedBox(height: 4),
              _totalRow(
                  'Total', (inv['total_pence'] ?? 0) as num,
                  bold: true),
              if (paid != null && balance != null) ...[
                const Divider(height: 24),
                _totalRow('Paid', paid),
                if (credited != null && credited != 0) ...[
                  const SizedBox(height: 4),
                  _totalRow('Credited', credited),
                ],
                const SizedBox(height: 4),
                _totalRow('Balance', balance, bold: true),
              ],
            ],
          ),
        ),
        if (money is Map) ...[
          const SizedBox(height: 12),
          _paymentsCard(payments, creditNotes),
        ],
        const SizedBox(height: 12),
        for (final line in rows) _lineCard(line),
        if (status == 'draft') ...[
          const SizedBox(height: 12),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: AccnomosColors.teal,
              minimumSize: const Size.fromHeight(52),
            ),
            onPressed: _send,
            child: const Text('Send via Outlook'),
          ),
        ],
        if (status == 'sent' && balance != null) ...[
          const SizedBox(height: 12),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: AccnomosColors.teal,
              minimumSize: const Size.fromHeight(52),
            ),
            onPressed: () => _recordPayment(balance),
            child: const Text('Record payment'),
          ),
          const SizedBox(height: 8),
          OutlinedButton(
            style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(52),
            ),
            onPressed: () => _createCreditNote(rows),
            child: const Text('Create credit note'),
          ),
          const SizedBox(height: 8),
          OutlinedButton(
            style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(52),
            ),
            onPressed: () => _voidInvoice(
                total, paid ?? 0, credited ?? 0),
            child: const Text('Void invoice'),
          ),
          const SizedBox(height: 4),
          const Text(
            'Voiding is refused while payments or credit notes stand — remove them first.',
            style: TextStyle(
              color: AccnomosColors.muted,
              fontSize: 12,
            ),
          ),
        ],
      ],
    );
  }

  /// Payments and credit notes from the runtime, each payment with Remove.
  Widget _paymentsCard(
      List<Map<String, dynamic>> payments,
      List<Map<String, dynamic>> creditNotes) {
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
            'Payments and history',
            style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
          ),
          const SizedBox(height: 8),
          if (payments.isEmpty && creditNotes.isEmpty)
            const Text(
              'No payments yet.',
              style: TextStyle(color: AccnomosColors.muted),
            )
          else ...[
            for (final payment in payments)
              _paymentRow(payment),
            for (final note in creditNotes)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        'Credit note ${(note['number'] ?? '').toString()} · '
                        '${gbp((note['applied_pence'] ?? 0) as num)}',
                        style: const TextStyle(
                            color: AccnomosColors.muted),
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ],
      ),
    );
  }

  Widget _paymentRow(Map<String, dynamic> payment) {
    final description =
        (payment['description'] ?? 'Payment').toString();
    final date = ukDate((payment['date'] ?? '').toString());
    final reference = (payment['reference'] ?? '').toString();
    final applied = gbp((payment['applied_pence'] ?? 0) as num);
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
                  '$date · $description'
                  '${reference.isNotEmpty ? ' · $reference' : ''}',
                ),
                Text(
                  applied,
                  style: const TextStyle(
                      fontWeight: FontWeight.w700),
                ),
              ],
            ),
          ),
          TextButton(
            onPressed: () => _removePayment(payment),
            style: TextButton.styleFrom(
              minimumSize: const Size(48, 48),
            ),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
  }

  Widget _totalRow(String label, num pence, {bool bold = false}) {
    final style = TextStyle(
      fontWeight: bold ? FontWeight.w800 : FontWeight.w600,
      fontSize: bold ? 17 : 14,
    );
    return Row(
      children: [
        Expanded(child: Text(label, style: style)),
        Text(gbp(pence), style: style),
      ],
    );
  }

  Widget _lineCard(Map<String, dynamic> line) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        minVerticalPadding: 10,
        title: Text(
          (line['description'] ?? '').toString(),
          style: const TextStyle(fontWeight: FontWeight.w700),
        ),
        subtitle: Text(
          'Qty ${(line['quantity'] ?? '').toString()} · '
          'VAT ${(line['vat_code'] ?? '').toString()}',
          style:
              const TextStyle(color: AccnomosColors.muted),
        ),
        trailing: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text(gbp((line['net_pence'] ?? 0) as num),
                style: const TextStyle(
                    fontWeight: FontWeight.w800)),
            Text(
                '+ ${gbp((line['vat_pence'] ?? 0) as num)} VAT',
                style: const TextStyle(
                    color: AccnomosColors.muted,
                    fontSize: 12)),
          ],
        ),
      ),
    );
  }
}
