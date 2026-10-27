import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../services/auth.dart';
import '../services/proposal_editing.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../services/sign_in_messages.dart';
import '../theme.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);

/// Builds a [RuntimeClient] for the settings screen. The app builds the
/// real client (with books credentials when signed in); tests inject a
/// fake that answers without touching the network.
typedef SettingsClientFactory = RuntimeClient Function(
    AppSettings settings, BooksAuth? books);

/// Autopilot levels, worded exactly like the web's Settings › Automation.
/// L0 exists on older installs but this screen only offers L1/L2.
const _autopilotOptions = [
  (
    value: 'L1',
    label: 'L1 Assist',
    description:
        'Imports, extracts, files and proposes; never posts or sends (default)',
  ),
  (
    value: 'L2',
    label: 'L2 Autopilot',
    description:
        'Also posts receipts that match a rule you saved (same supplier, VAT and treatment, \u2264 2\u00d7 the usual) \u2014 each one listed with Undo',
  ),
];

/// Settings in four expandable groups, mirroring the web's settings panels:
/// Connection, AI, Automation and Business. Keys and addresses stay on
/// this phone; only the web's own headers and bodies go to the reader.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({
    super.key,
    @visibleForTesting this.testAccount,
    @visibleForTesting this.testAccountReady = false,
    this.clientFactory,
  });

  /// Signed-in account to use without touching MSAL (tests only).
  @visibleForTesting
  final Account? testAccount;

  /// Skip the MSAL account lookup and use [testAccount] as-is (tests only).
  @visibleForTesting
  final bool testAccountReady;

  /// Builds the runtime client; null means the real [RuntimeClient].
  final SettingsClientFactory? clientFactory;

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
  final _profileAddress = TextEditingController();
  final _termsDays = TextEditingController();
  String? _termsError;
  final _bankName = TextEditingController();
  final _bankSort = TextEditingController();
  final _bankAccount = TextEditingController();
  int _stagger = 1;
  String _level = 'L1';

  /// Groups currently expanded; all four start open.
  final _open = {'connection', 'ai', 'automation', 'business'};

  AppSettings? _initial;
  Account? _account;
  bool _authChecked = false;
  String _mode = 'local';
  bool _obscureKey = true;

  bool _authBusy = false;
  String? _authError;

  bool _savingConnection = false;
  String? _connectionError;

  bool _testingAi = false;
  bool _savingAi = false;
  String? _aiTestMessage;
  bool _aiTestOk = false;

  List<Map<String, dynamic>>? _rules;
  bool _rulesLoading = false;
  String? _rulesError;
  String? _rulesNote;
  String? _removingKey;

  bool _inboxBusy = false;
  String? _inboxMessage;
  bool _inboxOk = false;

  Map<String, dynamic>? _profile;
  bool _profileLoading = false;
  String? _profileError;
  String? _profileSaveError;
  bool _savingBusiness = false;

  bool get _signedIn => _account != null;

  @override
  void initState() {
    super.initState();
    AppSettings.load().then((settings) {
      if (!mounted) return;
      setState(() {
        _initial = settings;
        _fill(settings);
      });
    });
    _loadAccount();
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
    _profileAddress.dispose();
    _termsDays.dispose();
    _bankName.dispose();
    _bankSort.dispose();
    _bankAccount.dispose();
    super.dispose();
  }

  void _fill(AppSettings settings) {
    _runtimeUrl.text = settings.runtimeUrl;
    _aiBaseUrl.text = settings.aiBaseUrl;
    _aiModel.text = settings.aiModel;
    _apiKey.text = settings.apiKey ?? '';
    _businessName.text = settings.businessName ?? '';
    _vrn.text = settings.vatNumber ?? '';
    _mode = settings.aiMode;
    _stagger = settings.vatStagger ?? 1;
    // This screen only offers L1/L2; anything else reads as L1 until saved.
    _level = settings.autopilotLevel == 'L2' ? 'L2' : 'L1';
    _startMonth.text = settings.vatStartMonth?.toString() ?? '';
  }

  Future<void> _loadAccount() async {
    if (widget.testAccountReady) {
      if (!mounted) return;
      setState(() {
        _account = widget.testAccount;
        _authChecked = true;
      });
      if (widget.testAccount != null) await _loadSignedInData();
      return;
    }
    Account? account;
    try {
      account = await _auth.account();
    } catch (_) {
      // No account (or no MSAL on this platform): signed-out fallback.
      account = null;
    }
    if (!mounted) return;
    setState(() {
      _account = account;
      _authChecked = true;
    });
    if (account != null) await _loadSignedInData();
  }

  /// Rules plus the invoice profile, both signed-in only.
  Future<void> _loadSignedInData() async {
    setState(() {
      _rulesLoading = true;
      _rulesError = null;
      _profileLoading = true;
      _profileError = null;
    });
    try {
      final rules = await (await _booksClient()).rules();
      if (!mounted) return;
      setState(() {
        _rules = rules;
        _rulesLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _rulesLoading = false;
        _rulesError = e.toString();
      });
    }
    try {
      final profile = await (await _booksClient()).invoiceProfile();
      if (!mounted) return;
      final bank = _bankOf(profile);
      setState(() {
        _profile = profile;
        _profileAddress.text = (profile['address'] ?? '').toString();
        _termsDays.text = (profile['terms_days'] ?? 30).toString();
        _bankName.text = (bank['account_name'] ?? '').toString();
        _bankSort.text = (bank['sort_code'] ?? '').toString();
        _bankAccount.text = (bank['account_number'] ?? '').toString();
        _profileLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _profileLoading = false;
        _profileError = e.toString();
      });
    }
  }

  static Map<String, dynamic> _bankOf(Map<String, dynamic> profile) {
    final bank = profile['bank'];
    if (bank is Map) return Map<String, dynamic>.from(bank);
    return <String, dynamic>{};
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
        apiKey: _apiKey.text.trim().isEmpty ? null : _apiKey.text.trim(),
        userEmail: _initial?.userEmail,
        businessName: _businessName.text.trim().isEmpty
            ? null
            : _businessName.text.trim(),
        vatNumber: _vrn.text.trim().isEmpty ? null : _vrn.text.trim(),
        vatStagger: _stagger,
        vatStartMonth: _startMonthValue() == -1 ? null : _startMonthValue(),
        autopilotLevel: _level,
      );

  /// Probe client for the AI test: no books headers, like the web's
  /// `/ai/test` call, which needs no sign-in.
  RuntimeClient _probeClient() =>
      widget.clientFactory?.call(_current(), null) ??
      RuntimeClient(_current());

  /// Books client for rules, inbox and the invoice profile. Throws the
  /// sign-in prompt when nobody is signed in.
  Future<RuntimeClient> _booksClient() async {
    final settings = _current();
    final factory = widget.clientFactory;
    if (factory != null) {
      return factory(
        settings,
        BooksAuth(
          graphToken: 'test-token',
          accountKind: 'personal',
          user: _account?.username,
          businessName: settings.businessName,
        ),
      );
    }
    final token = await _auth.token();
    Account? account = _account;
    try {
      account = await _auth.account() ?? account;
    } on MsalException {
      // Keep the account we already knew about.
    }
    if (mounted && account?.username != _account?.username) {
      setState(() => _account = account);
    }
    final user = account?.username ?? settings.userEmail;
    return RuntimeClient(
      settings,
      books: BooksAuth(
        graphToken: token,
        accountKind: _auth.kind == AccountKind.work ? 'work' : 'personal',
        user: (user != null && user.isNotEmpty) ? user : null,
        businessName: settings.businessName,
      ),
    );
  }

  /// Inbox checks read mail, so they ask for Mail.Read only now — never at
  /// sign-in — mirroring the web's extra mail scopes.
  Future<RuntimeClient> _mailClient() async {
    final settings = _current();
    final factory = widget.clientFactory;
    if (factory != null) {
      return factory(
        settings,
        BooksAuth(
          graphToken: 'test-token',
          accountKind: 'personal',
          user: _account?.username,
        ),
      );
    }
    final token = await _auth.tokenFor(AuthService.mailReadScopes);
    final user = _account?.username ?? settings.userEmail;
    return RuntimeClient(
      settings,
      books: BooksAuth(
        graphToken: token,
        accountKind: _auth.kind == AccountKind.work ? 'work' : 'personal',
        user: (user != null && user.isNotEmpty) ? user : null,
        businessName: settings.businessName,
      ),
    );
  }

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
            content:
                Text('Signed in as ${AuthService.displayName(account)}')),
      );
      await _loadSignedInData();
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
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Signed out.')),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() => _authError = friendlySignInMessage(e));
    } finally {
      if (mounted) setState(() => _authBusy = false);
    }
  }

  /// Disconnect, like the web: sign out and remove this device's sign-in
  /// and settings. Files stay in the user's OneDrive.
  Future<void> _disconnect() async {
    if (_authBusy) return;
    setState(() {
      _authBusy = true;
      _authError = null;
    });
    try {
      await _auth.signOut();
    } catch (e) {
      if (!mounted) return;
      // Still clear this device's settings below.
      setState(() => _authError = friendlySignInMessage(e));
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.clear();
    if (!mounted) return;
    final defaults = AppSettings(
      runtimeUrl: kDefaultRuntimeUrl,
      aiMode: 'local',
      aiBaseUrl: 'http://192.168.1.176:11434',
      aiModel: 'muse-glimmer:30b',
      vatStagger: 1,
      autopilotLevel: 'L1',
    );
    setState(() {
      _account = null;
      _authBusy = false;
      _initial = defaults;
      _fill(defaults);
      _vrnError = null;
      _startMonthError = null;
      _termsError = null;
      _rules = null;
      _rulesError = null;
      _rulesNote = null;
      _inboxMessage = null;
      _profile = null;
      _profileError = null;
      _profileSaveError = null;
      _aiTestMessage = null;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Disconnected.')),
    );
  }

  Future<void> _saveConnection() async {
    if (_savingConnection) return;
    final address = _runtimeUrl.text.trim();
    if (address.isEmpty) {
      setState(() =>
          _connectionError = 'Enter the reader address, e.g. http://10.0.2.2:8780.');
      return;
    }
    setState(() {
      _connectionError = null;
      _savingConnection = true;
    });
    await _current().save();
    if (!mounted) return;
    setState(() => _savingConnection = false);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Connection saved')),
    );
  }

  Future<void> _saveAi() async {
    if (_savingAi || !_signedIn) return;
    setState(() => _savingAi = true);
    await _current().save();
    if (!mounted) return;
    setState(() => _savingAi = false);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('AI settings saved')),
    );
  }

  /// Ask the reader whether the configured AI answers (`POST /ai/test`,
  /// the same body and headers the web sends). The result line mirrors
  /// the web: `Connected · model · detail` or `Not connected · detail`.
  Future<void> _testAi() async {
    if (_testingAi || !_signedIn) return;
    setState(() {
      _testingAi = true;
      _aiTestMessage = null;
    });
    try {
      final result = await _probeClient().aiTest();
      if (!mounted) return;
      final ok = result['ok'] == true;
      final model = (result['model'] ?? '').toString().trim();
      final detail =
          (result['detail'] ?? result['result'] ?? result.toString())
              .toString()
              .trim();
      setState(() {
        _aiTestOk = ok;
        _aiTestMessage = ok
            ? 'Connected${model.isEmpty ? '' : ' \u00b7 $model'} \u00b7 $detail'
            : 'Not connected \u00b7 $detail';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _aiTestOk = false;
        _aiTestMessage = 'Not connected \u00b7 ${e.toString()}';
      });
    } finally {
      if (mounted) setState(() => _testingAi = false);
    }
  }

  Future<void> _chooseLevel(String value) async {
    if (!_signedIn || _level == value) return;
    setState(() => _level = value);
    await _current().save();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Autopilot level saved')),
    );
  }

  Future<void> _removeRule(String supplierKey) async {
    if (_removingKey != null || !_signedIn) return;
    setState(() {
      _removingKey = supplierKey;
      _rulesNote = null;
    });
    try {
      await (await _booksClient()).removeRule(supplierKey);
      if (!mounted) return;
      setState(() {
        _rules = (_rules ?? [])
            .where((r) =>
                (r['supplier_key'] ?? '').toString() != supplierKey)
            .toList();
        _rulesNote =
            "Rule removed. Autopilot won't post for that supplier again.";
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Rule removed.')),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() => _rulesError = e.toString());
    } finally {
      if (mounted) setState(() => _removingKey = null);
    }
  }

  /// One inbox check: the last 14 days of mail with attachments, copied
  /// into 00 Inbox. Same arguments the web sends (`since_days: 14`,
  /// no dry run). Mail is only read.
  Future<void> _checkInbox() async {
    if (_inboxBusy || !_signedIn) return;
    setState(() {
      _inboxBusy = true;
      _inboxMessage = null;
      _inboxOk = false;
    });
    try {
      final result = await (await _mailClient()).mailScan(sinceDays: 14);
      if (!mounted) return;
      final saved = result['saved'];
      final n = saved is List ? saved.length : 0;
      final names = <String>[];
      final items = result['items'];
      if (items is List) {
        for (final item in items) {
          if (item is Map &&
              (item['name'] ?? '').toString().isNotEmpty) {
            names.add(item['name'].toString());
          }
        }
      } else if (saved is List) {
        for (final entry in saved) {
          if (entry is String && entry.isNotEmpty) {
            names.add(entry);
          } else if (entry is Map &&
              (entry['name'] ?? '').toString().isNotEmpty) {
            names.add(entry['name'].toString());
          }
        }
      }
      var line = '$n ${n == 1 ? 'file' : 'files'} imported';
      final scanned = result['scanned'];
      if (scanned is int) {
        line +=
            ' \u00b7 $scanned ${scanned == 1 ? 'email' : 'emails'} with attachments in the last 14 days';
      }
      final skipped = result['skipped_duplicates'];
      if (skipped is int && skipped > 0) {
        line += ' \u00b7 $skipped already in your books';
      }
      final errors = result['errors'];
      if (errors is List && errors.isNotEmpty) {
        final bits = <String>[];
        for (final error in errors) {
          if (error is Map) {
            bits.add(
                '${error['attachment'] ?? error['message'] ?? 'email'} (${error['error'] ?? 'not copied'})');
          }
        }
        if (bits.isNotEmpty) line += ' \u00b7 Could not copy: ${bits.join(' \u00b7 ')}';
      }
      if (names.isNotEmpty) line += '\n${names.take(5).join(', ')}';
      setState(() {
        _inboxOk = true;
        _inboxMessage = line;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _inboxOk = false;
        _inboxMessage = e.toString();
      });
    } finally {
      if (mounted) setState(() => _inboxBusy = false);
    }
  }

  Future<void> _reloadProfile() async {
    if (!_signedIn) return;
    setState(() {
      _profileLoading = true;
      _profileError = null;
    });
    try {
      final profile = await (await _booksClient()).invoiceProfile();
      if (!mounted) return;
      final bank = _bankOf(profile);
      setState(() {
        _profile = profile;
        _profileAddress.text = (profile['address'] ?? '').toString();
        _termsDays.text = (profile['terms_days'] ?? 30).toString();
        _bankName.text = (bank['account_name'] ?? '').toString();
        _bankSort.text = (bank['sort_code'] ?? '').toString();
        _bankAccount.text = (bank['account_number'] ?? '').toString();
        _profileLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _profileLoading = false;
        _profileError = e.toString();
      });
    }
  }

  /// Save the Business group: the name, VAT number and VAT period stay on
  /// this phone; the invoice basics (address, terms, bank) go to the
  /// invoice profile in OneDrive, keeping the shape it was loaded with —
  /// the same body the web sends.
  Future<void> _saveBusiness() async {
    if (_savingBusiness || !_signedIn) return;
    final vrnProblem = vrnError(_vrn.text);
    if (vrnProblem != null) {
      setState(() => _vrnError = vrnProblem);
      return;
    }
    if (_startMonthValue() == -1) {
      setState(() =>
          _startMonthError = 'Enter a month 1\u201312, or leave it empty.');
      return;
    }
    int? terms;
    if (_profile != null) {
      terms = int.tryParse(_termsDays.text.trim());
      if (terms == null) {
        setState(() => _termsError = 'Enter whole days from 0 to 120.');
        return;
      }
    }
    setState(() {
      _vrnError = null;
      _startMonthError = null;
      _termsError = null;
      _profileSaveError = null;
      _savingBusiness = true;
    });
    await _current().save();
    String? profileError;
    if (_profile != null) {
      final clamped = terms!.clamp(0, 120);
      try {
        final body = Map<String, dynamic>.from(_profile!);
        body['address'] = _profileAddress.text.trim();
        body['terms_days'] = clamped;
        body['bank'] = {
          'account_name': _bankName.text.trim(),
          'sort_code': _bankSort.text.trim(),
          'account_number': _bankAccount.text.trim(),
          'iban': _bankOf(_profile!)['iban'],
        };
        final saved =
            await (await _booksClient()).saveInvoiceProfile(body);
        if (!mounted) return;
        setState(() {
          _profile = saved;
          _termsDays.text = clamped.toString();
        });
      } catch (e) {
        profileError = e.toString();
      }
    }
    if (!mounted) return;
    setState(() {
      _savingBusiness = false;
      _profileSaveError = profileError;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
          content: Text(profileError == null
              ? 'Business settings saved'
              : 'Business name and VAT saved on this phone.')),
    );
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
          // A scroll view, not a list: every group builds (and keeps its
          // fields) whether or not it is on screen.
          : SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                _groupTile(
                  id: 'connection',
                  title: 'Connection',
                  disabledReason: null,
                  children: [
                    _accountSection(),
                    const SizedBox(height: 16),
                    _field(
                      fieldKey: 'readerField',
                      label: 'Reader address',
                      helper: 'The computer that reads your receipts. On the '
                          'Android emulator, http://10.0.2.2:8780 means your '
                          'own PC.',
                      controller: _runtimeUrl,
                      enabled: true,
                      error: _connectionError,
                      onChanged: (_) {
                        if (_connectionError != null) {
                          setState(() => _connectionError = null);
                        }
                      },
                    ),
                    const SizedBox(height: 12),
                    _saveButton(
                      label: 'Save connection',
                      busy: _savingConnection,
                      enabled: true,
                      onPressed: _saveConnection,
                    ),
                    const SizedBox(height: 16),
                    _disconnectSection(),
                  ],
                ),
                _groupTile(
                  id: 'ai',
                  title: 'AI',
                  disabledReason: _signedIn
                      ? null
                      : 'Sign in with Microsoft to change the AI settings.',
                  children: [
                    if (!_signedIn)
                      _disabledNote(
                          'Sign in with Microsoft to change the AI settings.'),
                    _modeOptions(),
                    if (_mode == 'local') ...[
                      const SizedBox(height: 12),
                      _field(
                        fieldKey: 'aiAddressField',
                        label: 'Local AI address',
                        helper: 'Where your on-machine model listens.',
                        controller: _aiBaseUrl,
                        enabled: _signedIn,
                      ),
                      const SizedBox(height: 12),
                      _field(
                        fieldKey: 'aiModelField',
                        label: 'Local model name',
                        helper: 'The model the reader asks on your machine.',
                        controller: _aiModel,
                        enabled: _signedIn,
                      ),
                    ],
                    if (_mode == 'key') ...[
                      const SizedBox(height: 12),
                      _field(
                        fieldKey: 'apiKeyField',
                        label: 'Muse API key',
                        helper:
                            'Only used for \u201cMuse Spark (key)\u201d. Stored on this phone only and sent straight to your reader.',
                        controller: _apiKey,
                        enabled: _signedIn,
                        obscure: _obscureKey,
                        suffix: IconButton(
                          constraints: const BoxConstraints(
                              minWidth: 48, minHeight: 48),
                          icon: Icon(_obscureKey
                              ? Icons.visibility_outlined
                              : Icons.visibility_off_outlined),
                          tooltip: _obscureKey ? 'Show key' : 'Hide key',
                          onPressed: () =>
                              setState(() => _obscureKey = !_obscureKey),
                        ),
                      ),
                    ],
                    const SizedBox(height: 12),
                    _saveButton(
                      label: 'Save AI settings',
                      busy: _savingAi,
                      enabled: _signedIn,
                      onPressed: _saveAi,
                    ),
                    const SizedBox(height: 12),
                    SizedBox(
                      width: double.infinity,
                      child: OutlinedButton(
                        style: OutlinedButton.styleFrom(
                          minimumSize: const Size.fromHeight(48),
                          shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(14)),
                        ),
                        onPressed:
                            (_testingAi || !_signedIn) ? null : _testAi,
                        child: _testingAi
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                    strokeWidth: 2),
                              )
                            : const Text('Test connection'),
                      ),
                    ),
                    if (_aiTestMessage != null) ...[
                      const SizedBox(height: 8),
                      _resultBox(
                          ok: _aiTestOk, message: _aiTestMessage!),
                    ],
                  ],
                ),
                _groupTile(
                  id: 'automation',
                  title: 'Automation',
                  disabledReason: _signedIn
                      ? null
                      : 'Sign in with Microsoft to use Autopilot and inbox checks.',
                  children: [
                    if (!_signedIn)
                      _disabledNote(
                          'Sign in with Microsoft to use Autopilot and inbox checks.'),
                    const Text('Autopilot level',
                        style: TextStyle(
                            fontWeight: FontWeight.w700,
                            color: AccnomosColors.ink)),
                    RadioGroup<String>(
                      groupValue: _level,
                      // Signed out the options only show the saved level.
                      onChanged: (v) {
                        if (!_signedIn || v == null) return;
                        _chooseLevel(v);
                      },
                      child: IgnorePointer(
                        ignoring: !_signedIn,
                        child: Opacity(
                          opacity: _signedIn ? 1.0 : 0.6,
                          child: Column(
                            children: [
                              ..._autopilotOptions.map(
                                  (opt) => RadioListTile<String>(
                                        value: opt.value,
                                        title: Text(opt.label,
                                            style: const TextStyle(
                                                fontWeight:
                                                    FontWeight.w700,
                                                color:
                                                    AccnomosColors.ink)),
                                        subtitle: Text(opt.description,
                                            style: const TextStyle(
                                                color: AccnomosColors.muted,
                                                fontSize: 12,
                                                height: 1.4)),
                                        contentPadding: EdgeInsets.zero,
                                        dense: true,
                                      )),
                            ],
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 8),
                    _rulesSection(),
                    const SizedBox(height: 16),
                    _inboxSection(),
                  ],
                ),
                _groupTile(
                  id: 'business',
                  title: 'Business',
                  disabledReason: _signedIn
                      ? null
                      : 'Sign in with Microsoft to edit business and invoice details.',
                  children: [
                    if (!_signedIn)
                      _disabledNote(
                          'Sign in with Microsoft to edit business and invoice details.'),
                    _field(
                      fieldKey: 'businessNameField',
                      label: 'Business name',
                      helper: 'Sent as X-Business-Name so the reader '
                          'attributes sales to your business.',
                      controller: _businessName,
                      enabled: _signedIn,
                    ),
                    const SizedBox(height: 12),
                    _field(
                      fieldKey: 'vrnField',
                      label: 'VAT number',
                      helper: 'Your 9-digit VAT registration number, e.g. '
                          '123456789. Checked for format only.',
                      controller: _vrn,
                      enabled: _signedIn,
                      error: _vrnError,
                      onChanged: (_) {
                        if (_vrnError != null) {
                          setState(() => _vrnError = vrnError(_vrn.text));
                        }
                      },
                    ),
                    const SizedBox(height: 12),
                    const Text('VAT quarter',
                        style: TextStyle(
                            fontWeight: FontWeight.w700,
                            color: AccnomosColors.ink)),
                    const SizedBox(height: 4),
                    const Text(
                        'Your HMRC stagger group. Home, VAT and Reports use it once saved; '
                        'until then the phone assumes Mar/Jun/Sep/Dec quarters.',
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
                      onSelectionChanged: !_signedIn
                          ? null
                          : (selected) =>
                              setState(() => _stagger = selected.first),
                    ),
                    const SizedBox(height: 12),
                    _field(
                      fieldKey: 'startMonthField',
                      label: 'Quarter starts in month (optional)',
                      helper: 'Only when your quarters start in a custom '
                          'month, e.g. 5 for May. Takes precedence over the stagger group above.',
                      controller: _startMonth,
                      enabled: _signedIn,
                      error: _startMonthError,
                      onChanged: (_) {
                        if (_startMonthError != null) {
                          setState(() => _startMonthError = null);
                        }
                      },
                    ),
                    const SizedBox(height: 16),
                    _profileSection(),
                    const SizedBox(height: 12),
                    _saveButton(
                      label: 'Save business settings',
                      busy: _savingBusiness,
                      enabled: _signedIn,
                      onPressed: _saveBusiness,
                    ),
                  ],
                ),
              ],
            ),
          ),
    );
  }

  Widget _groupTile({
    required String id,
    required String title,
    required String? disabledReason,
    required List<Widget> children,
  }) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: ExpansionTile(
        key: Key('group-$id'),
        title: Text(title,
            style: const TextStyle(
                fontWeight: FontWeight.w800,
                fontSize: 16,
                color: AccnomosColors.ink)),
        subtitle: disabledReason == null
            ? null
            : Text(disabledReason,
                style: const TextStyle(
                    color: AccnomosColors.muted,
                    fontSize: 12,
                    height: 1.4)),
        initiallyExpanded: _open.contains(id),
        onExpansionChanged: (open) => setState(() {
          if (open) {
            _open.add(id);
          } else {
            _open.remove(id);
          }
        }),
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16)),
        collapsedShape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16)),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        expandedAlignment: Alignment.topLeft,
        children: children,
      ),
    );
  }

  /// Pale reason line shown at the top of a group that needs sign-in.
  Widget _disabledNote(String reason) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: _warnBg,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _warnBorder),
      ),
      child: Text(reason,
          style: const TextStyle(color: _warnInk, height: 1.4)),
    );
  }

  /// AI result lines and inbox outcomes, mirroring the web's status boxes.
  Widget _resultBox({required bool ok, required String message}) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: ok ? AccnomosColors.tealTint : _warnBg,
        borderRadius: BorderRadius.circular(10),
        border: ok ? null : Border.all(color: _warnBorder),
      ),
      child: Text(
        message,
        style: TextStyle(
          color: ok ? AccnomosColors.tealDark : _warnInk,
          height: 1.4,
        ),
      ),
    );
  }

  Widget _modeOptions() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Where should the reading happen?',
            style: TextStyle(
                fontWeight: FontWeight.w700, color: AccnomosColors.ink)),
        RadioGroup<String>(
          groupValue: _mode,
          // Signed out the options only show the saved choice: taps and
          // dimming are handled below, the group itself stays inert.
          onChanged: (v) {
            if (!_signedIn || v == null) return;
            setState(() => _mode = v);
          },
          child: IgnorePointer(
            ignoring: !_signedIn,
            child: Opacity(
              opacity: _signedIn ? 1.0 : 0.6,
              child: Column(
                children: [
              RadioListTile<String>(
                value: 'local',
                title: const Row(
                  children: [
                    Expanded(
                        child: Text('On your own machine',
                            style: TextStyle(
                                fontWeight: FontWeight.w700,
                                color: AccnomosColors.ink))),
                    _PrivateBadge(),
                  ],
                ),
                subtitle: const Text(
                    'Muse Glimmer 30B, open weights, running on your computer. Receipts never leave your network.',
                    style: TextStyle(
                        color: AccnomosColors.muted,
                        fontSize: 12,
                        height: 1.4)),
                contentPadding: EdgeInsets.zero,
                dense: true,
              ),
              RadioListTile<String>(
                value: 'key',
                title: const Text('My own Meta API key',
                    style: TextStyle(
                        fontWeight: FontWeight.w700,
                        color: AccnomosColors.ink)),
                subtitle: const Text(
                    'Muse Spark via the Meta Model API. Fast, no hardware needed.',
                    style: TextStyle(
                        color: AccnomosColors.muted,
                        fontSize: 12,
                        height: 1.4)),
                contentPadding: EdgeInsets.zero,
                dense: true,
              ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _accountSection() {
    final account = _account;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Microsoft account',
            style: TextStyle(
                fontWeight: FontWeight.w700, color: AccnomosColors.ink)),
        const SizedBox(height: 4),
        Text(
          account == null
              ? (_authChecked
                  ? 'Your books live in your own OneDrive. Sign in to see them.'
                  : 'Checking\u2026')
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
                              fontWeight: FontWeight.w800, fontSize: 16)),
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
    );
  }

  Widget _disconnectSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Disconnect',
            style: TextStyle(
                fontWeight: FontWeight.w700, color: AccnomosColors.ink)),
        const SizedBox(height: 4),
        const Text(
            "Your files stay in your OneDrive. We remove this device's sign-in and settings.",
            style: TextStyle(
                color: AccnomosColors.muted, fontSize: 12, height: 1.4)),
        const SizedBox(height: 12),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton(
            style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(52),
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14)),
            ),
            onPressed: _authBusy ? null : _disconnect,
            child: const Text('Disconnect Accnomos'),
          ),
        ),
      ],
    );
  }

  Widget _rulesSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Autopilot rules',
            style: TextStyle(
                fontWeight: FontWeight.w700, color: AccnomosColors.ink)),
        const SizedBox(height: 4),
        const Text(
            'Saved when you tick \u201cAlways do this\u201d. Autopilot only posts when every check passes, the VAT number is the same and the total is no more than twice the usual.',
            style: TextStyle(
                color: AccnomosColors.muted, fontSize: 12, height: 1.4)),
        const SizedBox(height: 8),
        if (!_signedIn)
          _disabledNote(
              'Sign in with Microsoft to see the rules in your OneDrive.'),
        if (_signedIn && _rulesLoading)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 8),
            child: SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
          ),
        if (_signedIn && !_rulesLoading && _rulesError != null)
          Text(_rulesError!,
              style: const TextStyle(color: _warnInk, height: 1.4)),
        if (_signedIn && !_rulesLoading && _rulesError == null)
          ..._ruleRows(),
        if (_rulesNote != null) ...[
          const SizedBox(height: 8),
          Text(_rulesNote!,
              style: const TextStyle(
                  color: AccnomosColors.tealDark,
                  fontWeight: FontWeight.w700,
                  height: 1.4)),
        ],
      ],
    );
  }

  List<Widget> _ruleRows() {
    final rules = _rules ?? [];
    if (rules.isEmpty) {
      return const [
        Text('No rules yet. Tick \u201cAlways do this\u201d when you approve and the rule will appear here.',
            style: TextStyle(
                color: AccnomosColors.muted, fontSize: 12, height: 1.4)),
      ];
    }
    return [
      for (final rule in rules)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      ((rule['supplier_name'] ?? '').toString().isNotEmpty
                              ? rule['supplier_name']
                              : rule['supplier_key'])
                          .toString(),
                      style: const TextStyle(
                          fontWeight: FontWeight.w700,
                          color: AccnomosColors.ink),
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 2),
                    Text(
                      _ruleSummary(rule),
                      style: const TextStyle(
                          color: AccnomosColors.muted,
                          fontSize: 12,
                          height: 1.4),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              OutlinedButton(
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size(88, 40),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12)),
                ),
                onPressed: _removingKey != null
                    ? null
                    : () => _removeRule(
                        (rule['supplier_key'] ?? '').toString()),
                child: Text(_removingKey ==
                        (rule['supplier_key'] ?? '').toString()
                    ? 'Removing\u2026'
                    : 'Remove'),
              ),
            ],
          ),
        ),
    ];
  }

  /// `Category · code · usually £x · used Nx`, like the web's rules list.
  String _ruleSummary(Map<String, dynamic> rule) {
    final parts = <String>[];
    final category = (rule['category'] ?? '').toString();
    if (category.isNotEmpty) parts.add(category);
    final code = (rule['vat_code'] ?? '').toString();
    parts.add(code.isEmpty ? 'no code' : code);
    final typical = rule['typical_gross_pence'];
    if (typical is num) {
      parts.add('usually ${formatPence(typical.round())}');
    }
    final hits = rule['hits'];
    if (hits is num) parts.add('used ${hits.round()}\u00d7');
    return parts.join(' \u00b7 ');
  }

  Widget _inboxSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Outlook intake',
            style: TextStyle(
                fontWeight: FontWeight.w700, color: AccnomosColors.ink)),
        const SizedBox(height: 4),
        const Text(
            'Copies receipts and invoices attached to your emails into 00 Inbox. Mail is only read: nothing is moved, marked or deleted.',
            style: TextStyle(
                color: AccnomosColors.muted, fontSize: 12, height: 1.4)),
        const SizedBox(height: 12),
        if (!_signedIn)
          _disabledNote('Sign in with Microsoft to use this.'),
        if (_signedIn)
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: AccnomosColors.teal,
                minimumSize: const Size.fromHeight(52),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14)),
              ),
              onPressed: _inboxBusy ? null : _checkInbox,
              child: _inboxBusy
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: Colors.white),
                    )
                  : const Text('Check my inbox now',
                      style: TextStyle(
                          fontWeight: FontWeight.w800, fontSize: 16)),
            ),
          ),
        if (_inboxMessage != null) ...[
          const SizedBox(height: 8),
          _resultBox(ok: _inboxOk, message: _inboxMessage!),
        ],
      ],
    );
  }

  Widget _profileSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('On your invoices',
            style: TextStyle(
                fontWeight: FontWeight.w700, color: AccnomosColors.ink)),
        const SizedBox(height: 4),
        const Text(
            'Your address, payment terms and bank details as they print on every invoice. Kept in your OneDrive, so every device prints the same.',
            style: TextStyle(
                color: AccnomosColors.muted, fontSize: 12, height: 1.4)),
        const SizedBox(height: 8),
        if (!_signedIn)
          _disabledNote('Sign in with Microsoft to set this up.'),
        if (_signedIn && _profileLoading)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 8),
            child: SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
          ),
        if (_signedIn && !_profileLoading && _profileError != null) ...[
          Text(_profileError!,
              style: const TextStyle(color: _warnInk, height: 1.4)),
          const SizedBox(height: 8),
          OutlinedButton(
            onPressed: _reloadProfile,
            child: const Text('Try again'),
          ),
        ],
        if (_signedIn && !_profileLoading && _profile != null) ...[
          _field(
            fieldKey: 'profileAddressField',
            label: 'Address',
            helper: 'Printed at the top of your invoices.',
            controller: _profileAddress,
            enabled: _signedIn,
            maxLines: 3,
          ),
          const SizedBox(height: 12),
          _field(
            fieldKey: 'termsField',
            label: 'Payment terms (days)',
            helper: 'Whole days from 0 to 120.',
            controller: _termsDays,
            enabled: _signedIn,
            keyboardType: TextInputType.number,
            error: _termsError,
            onChanged: (_) {
              if (_termsError != null) {
                setState(() => _termsError = null);
              }
            },
          ),
          const SizedBox(height: 12),
          const Text('Bank details for payment',
              style: TextStyle(
                  fontWeight: FontWeight.w700,
                  color: AccnomosColors.ink)),
          const SizedBox(height: 8),
          _field(
            fieldKey: 'bankNameField',
            label: 'Account name',
            helper: 'Who the invoice tells customers to pay.',
            controller: _bankName,
            enabled: _signedIn,
          ),
          const SizedBox(height: 12),
          _field(
            fieldKey: 'bankSortField',
            label: 'Sort code',
            helper: 'E.g. 12-34-56.',
            controller: _bankSort,
            enabled: _signedIn,
            keyboardType: TextInputType.number,
          ),
          const SizedBox(height: 12),
          _field(
            fieldKey: 'bankAccountField',
            label: 'Account number',
            helper: 'Your 8-digit account number.',
            controller: _bankAccount,
            enabled: _signedIn,
            keyboardType: TextInputType.number,
          ),
        ],
        if (_profileSaveError != null) ...[
          const SizedBox(height: 8),
          Text(_profileSaveError!,
              style: const TextStyle(color: _warnInk, height: 1.4)),
        ],
      ],
    );
  }

  Widget _saveButton({
    required String label,
    required bool busy,
    required bool enabled,
    required VoidCallback onPressed,
  }) {
    return SizedBox(
      width: double.infinity,
      child: FilledButton(
        style: FilledButton.styleFrom(
          backgroundColor: AccnomosColors.teal,
          minimumSize: const Size.fromHeight(52),
          shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(14)),
        ),
        onPressed: (!enabled || busy) ? null : onPressed,
        child: busy
            ? const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(
                    strokeWidth: 2, color: Colors.white),
              )
            : Text(label,
                style: const TextStyle(
                    fontWeight: FontWeight.w800, fontSize: 16)),
      ),
    );
  }

  Widget _field({
    required String fieldKey,
    required String label,
    required String helper,
    required TextEditingController controller,
    bool enabled = true,
    bool obscure = false,
    Widget? suffix,
    String? error,
    ValueChanged<String>? onChanged,
    int maxLines = 1,
    TextInputType? keyboardType,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: const TextStyle(
                fontWeight: FontWeight.w700, color: AccnomosColors.ink)),
        const SizedBox(height: 6),
        TextField(
          key: Key(fieldKey),
          controller: controller,
          enabled: enabled,
          obscureText: obscure,
          autocorrect: false,
          maxLines: obscure ? 1 : maxLines,
          keyboardType: maxLines > 1 ? TextInputType.multiline : keyboardType,
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

class _PrivateBadge extends StatelessWidget {
  const _PrivateBadge();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: AccnomosColors.tealTint,
        borderRadius: BorderRadius.circular(999),
      ),
      child: const Text('MOST PRIVATE',
          style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w800,
              color: AccnomosColors.tealDark)),
    );
  }
}


