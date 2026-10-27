import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';
import 'package:url_launcher/url_launcher.dart';

import '../services/auth.dart';
import '../services/graph.dart';
import '../theme.dart';

/// A live view of the Accnomos books folder in the user's own cloud.
///
/// Signed in: top-level folders with counts and last modified; tapping a
/// folder lists its files with size and date, each with an "Open" button
/// that launches the OneDrive link. Signed out: a sign-in prompt.
class FilesScreen extends StatefulWidget {
  const FilesScreen({super.key});

  @override
  State<FilesScreen> createState() => _FilesScreenState();
}

class _FilesScreenState extends State<FilesScreen> {
  final AuthService _auth = AuthService();
  final GraphService _graph = GraphService();

  Account? _account;
  bool _authChecked = false;
  bool _loading = false;
  String? _error;

  /// Path segments below the books root, e.g. `['05 VAT returns']`.
  final List<String> _trail = [];

  List<DriveItem> _items = const [];

  String get _relPath => _trail.join('/');

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _graph.close();
    super.dispose();
  }

  Future<void> _load() async {
    Account? account;
    try {
      account = await _auth.account();
    } on MsalException {
      account = null;
    }
    if (!mounted) return;
    setState(() {
      _account = account;
      _authChecked = true;
    });
    if (account != null) await _refresh();
  }

  Future<void> _refresh() async {
    if (_account == null || _loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final token = await _auth.token();
      final items = await _graph.listChildren(
        token,
        _auth.kind,
        _relPath,
      );
      if (!mounted) return;
      setState(() => _items = items);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error =
          e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _open(DriveItem item) async {
    final url = item.webUrl;
    if (url == null || url.isEmpty) {
      _say('That file has no link yet.');
      return;
    }
    final launched = await launchUrl(
      Uri.parse(url),
      mode: LaunchMode.externalApplication,
    );
    if (!launched && mounted) _say('Could not open that file.');
  }

  void _say(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }

  void _enter(DriveItem item) {
    setState(() {
      _trail.add(item.name);
      _items = const [];
    });
    _refresh();
  }

  void _up() {
    if (_trail.isEmpty) return;
    setState(() {
      _trail.removeLast();
      _items = const [];
    });
    _refresh();
  }

  @override
  Widget build(BuildContext context) {
    final inFolder = _trail.isNotEmpty;
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        automaticallyImplyLeading: false,
        title: Text(
          inFolder ? _trail.last : 'Files',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        leading: inFolder
            ? IconButton(
                icon: const Icon(Icons.arrow_back),
                tooltip: 'Back',
                constraints:
                    const BoxConstraints(minWidth: 48, minHeight: 48),
                onPressed: _up,
              )
            : null,
      ),
      body: !_authChecked
          ? const Center(child: CircularProgressIndicator())
          : _account == null
              ? _signInPrompt()
              : _loading && _items.isEmpty
                  ? const Center(child: CircularProgressIndicator())
                  : _fileList(),
    );
  }

  Widget _signInPrompt() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: const Color(0xFFE3E1D8)),
          ),
          child: const Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Your files live in your own cloud',
                style: TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: 16,
                  color: AccnomosColors.ink,
                ),
              ),
              SizedBox(height: 6),
              Text(
                'Sign in with Microsoft to browse the Accnomos folder '
                'in your OneDrive — receipts, returns and the ledger.',
                style: TextStyle(
                    color: AccnomosColors.muted, height: 1.4),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _fileList() {
    if (_error != null && _items.isEmpty) {
      return ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _errorBox(_error!),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: AccnomosColors.teal,
                minimumSize: const Size.fromHeight(52),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14)),
              ),
              onPressed: _refresh,
              child: const Text('Try again',
                  softWrap: false,
                  style: TextStyle(fontWeight: FontWeight.w800)),
            ),
          ),
        ],
      );
    }
    if (_items.isEmpty) {
      return RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(24),
          children: const [
            Text(
              'Nothing here yet. Photograph a receipt to get started.',
              textAlign: TextAlign.center,
              style: TextStyle(
                  color: AccnomosColors.muted, height: 1.4),
            ),
          ],
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView.separated(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.symmetric(vertical: 8),
        itemCount: _items.length,
        separatorBuilder: (_, _) => const Divider(
          height: 1,
          indent: 72,
          color: Color(0xFFE3E1D8),
        ),
        itemBuilder: (context, i) {
          final item = _items[i];
          return item.isFolder ? _folderRow(item) : _fileRow(item);
        },
      ),
    );
  }

  Widget _errorBox(String text) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF7ED),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFFF3C892)),
      ),
      child: Text(text,
          style:
              const TextStyle(color: Color(0xFF8A3F06), height: 1.4)),
    );
  }

  String _subtitle(DriveItem item) {
    final parts = <String>[];
    if (item.isFolder) {
      parts.add(item.countLabel);
    } else {
      parts.add(item.sizeLabel);
    }
    if (item.dateLabel.isNotEmpty) {
      parts.add('Modified ${item.dateLabel}');
    }
    return parts.join(' · ');
  }

  Widget _folderRow(DriveItem item) {
    return ListTile(
      contentPadding:
          const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      leading: const CircleAvatar(
        backgroundColor: AccnomosColors.tealTint,
        child: Icon(Icons.folder_outlined,
            color: AccnomosColors.tealDark),
      ),
      title: Text(item.name,
          softWrap: false, overflow: TextOverflow.ellipsis),
      subtitle: Text(_subtitle(item)),
      trailing: const Icon(Icons.chevron_right,
          color: AccnomosColors.muted),
      onTap: () => _enter(item),
    );
  }

  Widget _fileRow(DriveItem item) {
    return ListTile(
      contentPadding:
          const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      leading: const CircleAvatar(
        backgroundColor: Color(0xFFF1EFE7),
        child:
            Icon(Icons.receipt_long_outlined,
                color: AccnomosColors.muted),
      ),
      title: Text(item.name,
          softWrap: false, overflow: TextOverflow.ellipsis),
      subtitle: Text(_subtitle(item)),
      trailing: OutlinedButton(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(72, 40),
          padding: const EdgeInsets.symmetric(horizontal: 8),
          shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12)),
        ),
        onPressed: () => _open(item),
        child: const Text('Open', softWrap: false),
      ),
    );
  }
}
