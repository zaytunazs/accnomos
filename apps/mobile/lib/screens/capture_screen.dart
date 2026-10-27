import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/proposal.dart';
import '../services/auth.dart';
import '../services/graph.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);

/// Max file size for a direct Graph upload (same 4 MB limit as the web intake).
const _maxUploadBytes = 4 * 1024 * 1024;

/// Photograph or pick a receipt and get it into the books.
///
/// Signed in: the photo is uploaded to the user's own `00 Inbox` folder on
/// OneDrive (Graph PUT, like the web's `UploadToInbox.tsx`), then `scan()` is
/// called. Pops `true` so Review reloads. Signed out: the receipt is read
/// directly and the resulting [Proposal] is popped back to the review list.
class CaptureScreen extends StatefulWidget {
  const CaptureScreen({super.key});

  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends State<CaptureScreen> {
  final ImagePicker _picker = ImagePicker();
  final AuthService _auth = AuthService();
  AppSettings? _settings;
  Account? _account;
  bool _authChecked = false;
  XFile? _photo;
  bool _reading = false;
  String? _error;
  String? _doneMessage;

  /// Inbox file name once the photo is uploaded (signed-in flow). While set,
  /// the action button becomes 'Scan now' instead of 'Upload'.
  String? _uploadedName;

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
    } on MsalException {
      account = null;
    }
    if (mounted) {
      setState(() {
        _settings = settings;
        _account = account;
        _authChecked = true;
      });
    }
  }

  bool get _signedIn => _account != null;

  bool get _localMode => _settings == null || _settings!.aiMode != 'key';

  String _friendly(Object e) => e.toString().replaceFirst('Exception: ', '');

  Future<void> _pick(ImageSource source) async {
    try {
      final file = await _picker.pickImage(source: source);
      if (file == null || !mounted) return;
      setState(() {
        _photo = file;
        _error = null;
        _doneMessage = null;
        _uploadedName = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    }
  }

  /// Signed-out flow: read the receipt directly with the runtime.
  Future<void> _read() async {
    final settings = _settings;
    final photo = _photo;
    if (settings == null || photo == null || _reading) return;
    setState(() {
      _reading = true;
      _error = null;
    });
    try {
      final json = await RuntimeClient(settings).extract(File(photo.path));
      if (!mounted) return;
      Navigator.of(context).pop(Proposal.fromRuntime(json));
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = _friendly(e);
        _reading = false;
      });
    }
  }

  /// Signed-in flow, step 1: upload to `00 Inbox`. Shows the file name and
  /// turns the action button into 'Scan now'.
  Future<void> _upload() async {
    final settings = _settings;
    final photo = _photo;
    if (settings == null || photo == null || _reading) return;
    setState(() {
      _reading = true;
      _error = null;
      _doneMessage = null;
    });
    final graphs = GraphService();
    try {
      final bytes = await File(photo.path).readAsBytes();
      if (bytes.length > _maxUploadBytes) {
        throw GraphException(
            'That photo is over 4 MB — please use a smaller photo for now.');
      }
      final token = await _auth.token();
      final kind = _auth.kind;
      await graphs.ensureFolder(token, kind, '00 Inbox');
      final inboxName = _inboxName(photo.path);
      await graphs.putFileBytes(
        token: token,
        kind: kind,
        relPath: '00 Inbox/$inboxName',
        bytes: bytes,
        contentType: _contentType(photo.path),
      );
      if (!mounted) return;
      setState(() {
        _reading = false;
        _uploadedName = inboxName;
        _doneMessage = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = _friendly(e);
        _reading = false;
      });
    } finally {
      graphs.close();
    }
  }

  /// Signed-in flow, step 2: scan the inbox. Pops `true` when clean.
  Future<void> _scanNow() async {
    final settings = _settings;
    if (settings == null || _reading) return;
    setState(() {
      _reading = true;
      _error = null;
      _doneMessage = null;
    });
    try {
      final account = await _auth.account();
      final user = account?.username ?? settings.userEmail;
      final kind = _auth.kind;
      final outcome = await RuntimeClient(
        settings,
        books: BooksAuth(
          graphToken: await _auth.token(),
          accountKind: kind == AccountKind.work ? 'work' : 'personal',
          user: (user != null && user.isNotEmpty) ? user : null,
          businessName: settings.businessName,
        ),
      ).scan();
      if (!mounted) return;
      final errors = outcome.errors;
      if (errors.isEmpty) {
        Navigator.of(context).pop(true);
      } else {
        setState(() {
          _reading = false;
          _doneMessage =
              'Uploaded · ${outcome.proposals.length} proposal${outcome.proposals.length == 1 ? '' : 's'} ready';
          _error = errors
              .map((e) => '${e.path}: ${e.error}')
              .join('\n');
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = _friendly(e);
        _reading = false;
      });
    }
  }

  static String _inboxName(String path) {
    final base = path.split(Platform.pathSeparator).last;
    final dot = base.lastIndexOf('.');
    final ext = dot >= 0 ? base.substring(dot).toLowerCase() : '.jpg';
    final stamp = DateTime.now()
        .toIso8601String()
        .replaceAll(RegExp(r'[^0-9]'), '')
        .substring(0, 14);
    return 'receipt-$stamp$ext';
  }

  static String _contentType(String path) {
    final lower = path.toLowerCase();
    if (lower.endsWith('.png')) return 'image/png';
    if (lower.endsWith('.pdf')) return 'application/pdf';
    if (lower.endsWith('.heic') || lower.endsWith('.heif')) {
      return 'image/heic';
    }
    return 'image/jpeg';
  }

  @override
  Widget build(BuildContext context) {
    final progressText = _signedIn
        ? (_uploadedName == null
            ? 'Uploading to your 00 Inbox…'
            : 'Scanning your inbox…')
        : _localMode
            ? 'Reading on your machine… (about 20–60 s)'
            : 'Reading with Muse Spark…';
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          'Add a receipt',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
      ),
      body: !_authChecked
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_signedIn)
                  Container(
                    width: double.infinity,
                    margin: const EdgeInsets.only(bottom: 12),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AccnomosColors.tealTint,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: const Text(
                      'Signed in — the photo goes to the 00 Inbox folder in your own OneDrive. Press “Scan now” to read it.',
                      style: TextStyle(
                          color: AccnomosColors.tealDark, height: 1.4),
                    ),
                  ),
                if (_photo == null) ...[
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      style: FilledButton.styleFrom(
                        backgroundColor: AccnomosColors.teal,
                        minimumSize: const Size.fromHeight(64),
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14)),
                      ),
                      onPressed: () => _pick(ImageSource.camera),
                      icon: const Icon(Icons.photo_camera_outlined),
                      label: const Text('Take a photo',
                          style: TextStyle(
                              fontWeight: FontWeight.w800, fontSize: 16)),
                    ),
                  ),
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      style: OutlinedButton.styleFrom(
                        minimumSize: const Size.fromHeight(64),
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14)),
                      ),
                      onPressed: () => _pick(ImageSource.gallery),
                      icon: const Icon(Icons.photo_library_outlined),
                      label: const Text('Choose from gallery',
                          style: TextStyle(
                              fontWeight: FontWeight.w700, fontSize: 16)),
                    ),
                  ),
                ] else ...[
                  ClipRRect(
                    borderRadius: BorderRadius.circular(16),
                    child: Image.file(
                      File(_photo!.path),
                      height: 320,
                      width: double.infinity,
                      fit: BoxFit.cover,
                    ),
                  ),
                  const SizedBox(height: 8),
                  TextButton(
                    style: TextButton.styleFrom(
                        minimumSize: const Size.fromHeight(48)),
                    onPressed: _reading
                        ? null
                        : () => setState(() {
                              _photo = null;
                              _error = null;
                              _doneMessage = null;
                              _uploadedName = null;
                            }),
                    child: const Text('Choose a different photo'),
                  ),
                  const SizedBox(height: 4),
                  if (_signedIn && _uploadedName != null)
                    Container(
                      width: double.infinity,
                      margin: const EdgeInsets.only(bottom: 8),
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: AccnomosColors.tealTint,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.description_outlined,
                              color: AccnomosColors.tealDark),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Text(
                              'Uploaded $_uploadedName to your 00 Inbox.',
                              style: const TextStyle(
                                  color: AccnomosColors.tealDark,
                                  height: 1.4),
                            ),
                          ),
                        ],
                      ),
                    ),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      style: FilledButton.styleFrom(
                        backgroundColor: AccnomosColors.teal,
                        minimumSize: const Size.fromHeight(52),
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14)),
                      ),
                      onPressed: (_reading || _settings == null)
                          ? null
                          : (_signedIn
                              ? (_uploadedName == null
                                  ? _upload
                                  : _scanNow)
                              : _read),
                      child: Text(
                          _signedIn
                              ? (_uploadedName == null
                                  ? 'Upload'
                                  : 'Scan now')
                              : 'Read with Meta AI',
                          style: const TextStyle(
                              fontWeight: FontWeight.w800, fontSize: 16)),
                    ),
                  ),
                  if (_reading) ...[
                    const SizedBox(height: 16),
                    Container(
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        color: AccnomosColors.tealTint,
                        borderRadius: BorderRadius.circular(14),
                      ),
                      child: Row(
                        children: [
                          const CircularProgressIndicator(
                              color: AccnomosColors.tealDark),
                          const SizedBox(width: 16),
                          Expanded(
                            child: Text(progressText,
                                style: const TextStyle(
                                    color: AccnomosColors.tealDark,
                                    fontWeight: FontWeight.w700,
                                    height: 1.4)),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
                if (_doneMessage != null)
                  Container(
                    width: double.infinity,
                    margin: const EdgeInsets.only(top: 12),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AccnomosColors.tealTint,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(_doneMessage!,
                            style: const TextStyle(
                                color: AccnomosColors.tealDark,
                                height: 1.4)),
                        const SizedBox(height: 8),
                        SizedBox(
                          width: double.infinity,
                          child: FilledButton(
                            style: FilledButton.styleFrom(
                              backgroundColor: AccnomosColors.teal,
                              minimumSize: const Size.fromHeight(48),
                              shape: RoundedRectangleBorder(
                                  borderRadius:
                                      BorderRadius.circular(14)),
                            ),
                            onPressed: () =>
                                Navigator.of(context).pop(true),
                            child: const Text('Back to review'),
                          ),
                        ),
                      ],
                    ),
                  ),
                if (_error != null) _errorBox(),
              ],
            ),
    );
  }

  Widget _errorBox() {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: _warnBg,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _warnBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(_error ?? 'Something went wrong.',
              style: const TextStyle(color: _warnInk, height: 1.4)),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
              style: OutlinedButton.styleFrom(
                foregroundColor: _warnInk,
                side: const BorderSide(color: _warnInk),
                minimumSize: const Size.fromHeight(48),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14)),
              ),
              onPressed: (_photo == null || _reading)
                  ? null
                  : (_signedIn
                      ? (_uploadedName == null ? _upload : _scanNow)
                      : _read),
              child: const Text('Retry'),
            ),
          ),
        ],
      ),
    );
  }
}
