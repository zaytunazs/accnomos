import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/proposal.dart';
import '../services/auth.dart';
import '../services/capture_queue.dart';
import '../services/graph.dart';
import '../services/image_prep.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../services/share_intent.dart';
import '../theme.dart';
import '../widgets/crop_editor.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);

/// Max file size for a direct Graph upload (same 4 MB limit as the web intake).
const _maxUploadBytes = 4 * 1024 * 1024;

/// Photo extensions the preview editor can rotate and crop.
const _imageExts = {'.jpg', '.png', '.heic', '.heif'};

/// Photograph or pick several receipts and get them into the books.
///
/// Signed in: every photo lands in the user's own `00 Inbox` folder on
/// OneDrive as `receipt-<stamp>-<n>.<ext>` (Graph PUT, like the web's
/// `UploadToInbox.tsx`), then `scan()` runs once. Pops a
/// [CaptureScanSummary] so Review reloads with an "N new, M need a look"
/// summary. Signed out: each photo is read directly and the resulting
/// [Proposal]s are popped back as a list.
///
/// Files shared from another app (gallery, email) land in the same queue.
/// With no network the queue is kept in app storage and retried when the
/// app returns to the foreground — every state ends somewhere visible,
/// never on a spinner that never ends.
class CaptureScreen extends StatefulWidget {
  const CaptureScreen({super.key});

  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends State<CaptureScreen>
    with WidgetsBindingObserver {
  final ImagePicker _picker = ImagePicker();
  final AuthService _auth = AuthService();
  AppSettings? _settings;
  Account? _account;
  bool _authChecked = false;

  /// One stamp per visit: `receipt-<stamp>-<n>.<ext>`.
  late final String _stamp = stampFor(DateTime.now());

  List<CaptureItem> _items = [];
  bool _busy = false;
  bool _scanning = false;
  int _readingTotal = 0;
  int _readingDone = 0;
  bool _offline = false;
  String? _error;
  String? _doneMessage;
  List<ScanFileError> _scanErrors = const [];
  CaptureScanSummary? _summary;

  bool get _signedIn => _account != null;

  String _friendly(Object e) => e.toString().replaceFirst('Exception: ', '');

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _load();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  /// Foreground return: pick up newly shared files and retry the queue.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _collectShared().then((added) {
        if (!mounted || _busy || _scanning) return;
        final pending =
            _items.any((i) => i.status != CaptureStatus.uploaded);
        if ((added || pending) && _signedIn) _uploadAll(autoScan: false);
      });
    }
  }

  Future<void> _load() async {
    final settings = await AppSettings.load();
    Account? account;
    try {
      account = await _auth.account();
    } catch (_) {
      // No account (or no MSAL on this platform): signed-out fallback.
      account = null;
    }
    final kept = await CaptureQueueStore.load();
    if (!mounted) return;
    setState(() {
      _settings = settings;
      _account = account;
      _authChecked = true;
      // Anything left mid-upload by a restart goes back to the queue.
      _items = kept;
    });
    await _persist();
    await _collectShared();
  }

  /// Files shared from another app since the last check join the queue.
  /// Returns true when at least one file was added.
  Future<bool> _collectShared() async {
    final paths = await ShareIntent.initialSharedFiles();
    if (paths.isEmpty || !mounted) return false;
    await _stagePaths(paths, shared: true);
    return true;
  }

  /// Copies [paths] into app storage and queues them. Nothing referenced
  /// outside our own directory, so gallery originals can move or vanish.
  Future<void> _stagePaths(List<String> paths, {bool shared = false}) async {
    final dir =
        await Directory('${Directory.systemTemp.path}/accnomos_capture')
            .create(recursive: true);
    var added = 0;
    var skipped = 0;
    final items = List<CaptureItem>.of(_items);
    for (final path in paths) {
      try {
        final ext = extFor(path);
        if (!_imageExts.contains(ext) && ext != '.pdf') {
          skipped++;
          continue;
        }
        final staged = File(
            '${dir.path}/cap-${DateTime.now().microsecondsSinceEpoch}-$added$ext');
        await File(path).copy(staged.path);
        items.add(CaptureItem(path: staged.path, ext: ext));
        added++;
      } catch (_) {
        skipped++;
      }
    }
    if (!mounted) return;
    setState(() {
      _items = items;
      _offline = false;
      _error = skipped > 0 && added == 0
          ? (shared
              ? 'That shared file is not a photo or PDF, so it was skipped.'
              : 'That file is not a photo, so it was skipped.')
          : null;
    });
    await _persist();
  }

  Future<void> _persist() =>
      CaptureQueueStore.save(_items).catchError((_) {});

  void _updateItem(String id, CaptureItem Function(CaptureItem) f) {
    setState(() {
      _items = [for (final i in _items) i.id == id ? f(i) : i];
    });
    _persist();
  }

  Future<void> _removeItem(CaptureItem item) async {
    setState(() {
      _items = _items.where((i) => i.id != item.id).toList();
    });
    await _persist();
    try {
      await File(item.path).delete();
    } catch (_) {
      // Staged copy already gone; the queue entry is what mattered.
    }
  }

  Future<void> _takePhoto() async {
    try {
      final file = await _picker.pickImage(source: ImageSource.camera);
      if (file == null || !mounted) return;
      await _stagePaths([file.path]);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    }
  }

  Future<void> _pickGallery() async {
    try {
      final files = await _picker.pickMultiImage();
      if (files.isEmpty || !mounted) return;
      await _stagePaths([for (final f in files) f.path]);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    }
  }

  int get _pendingCount => _items
      .where((i) =>
          i.status == CaptureStatus.queued ||
          i.status == CaptureStatus.failed)
      .length;

  int get _uploadedCount =>
      _items.where((i) => i.status == CaptureStatus.uploaded).length;

  /// Upload every queued item in queue order, then scan once.
  Future<void> _uploadAll({bool autoScan = true}) async {
    if (_settings == null || _busy || _signedIn == false) return;
    setState(() {
      _busy = true;
      _error = null;
      _doneMessage = null;
      _scanErrors = const [];
      _offline = false;
    });
    var uploadedNow = 0;
    try {
      final token = await _auth.token();
      final kind = _auth.kind;
      final graphs = GraphService();
      try {
        await graphs.ensureFolder(token, kind, '00 Inbox');
        for (var n = 0; n < _items.length; n++) {
          final item = _items[n];
          if (item.status != CaptureStatus.queued &&
              item.status != CaptureStatus.failed) {
            continue;
          }
          _updateItem(
              item.id,
              (i) => i.copyWith(
                  status: CaptureStatus.uploading, clearError: true));
          try {
            final inboxName =
                inboxNameFor(_stamp, n, item.isPdf ? '.pdf' : '.jpg');
            await _uploadOne(graphs, token, kind, item, inboxName);
            _updateItem(
                item.id,
                (i) => i.copyWith(
                    status: CaptureStatus.uploaded,
                    inboxName: inboxName,
                    clearError: true));
            uploadedNow++;
          } on SocketException catch (_) {
            // No network: keep the item queued, stop this run, say so.
            _updateItem(item.id,
                (i) => i.copyWith(status: CaptureStatus.queued));
            if (mounted) setState(() => _offline = true);
            break;
          } catch (e) {
            _updateItem(item.id,
                (i) => i.copyWith(status: CaptureStatus.failed, error: _friendly(e)));
          }
        }
      } finally {
        graphs.close();
      }
    } on SocketException catch (_) {
      if (mounted) setState(() => _offline = true);
    } catch (e) {
      if (mounted) setState(() => _error = _friendly(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
    if (!mounted) return;
    if (uploadedNow > 0 && autoScan && !_offline) {
      await _scanOnce();
    } else if (uploadedNow > 0 && _offline) {
      setState(() => _doneMessage =
          'Uploaded $uploadedNow — scan when you are back online.');
    }
  }

  /// A single upload: missing staged files and oversized bytes fail with a
  /// message instead of hanging or vanishing.
  Future<void> _uploadOne(
    GraphService graphs,
    String token,
    AccountKind kind,
    CaptureItem item,
    String inboxName,
  ) async {
    final staged = File(item.path);
    if (!await staged.exists()) {
      throw const FileSystemException(
          'That photo is no longer on this phone (cache cleared).');
    }
    final raw = await staged.readAsBytes();
    final bytes = await ImagePrep.preparedBytes(
      src: raw,
      quarters: item.rotationQuarters,
      crop: item.crop,
      isPdf: item.isPdf,
    );
    if (bytes.length > _maxUploadBytes) {
      throw GraphException(
          'That photo is over 4 MB — please use a smaller photo for now.');
    }
    await graphs.putFileBytes(
      token: token,
      kind: kind,
      relPath: '00 Inbox/$inboxName',
      bytes: bytes,
      contentType: contentTypeFor(inboxName),
    );
  }

  /// Retry one failed (or queued) item on its own.
  Future<void> _retryItem(CaptureItem item) async {
    if (_settings == null || _busy || !_signedIn) return;
    setState(() {
      _busy = true;
      _error = null;
      _offline = false;
    });
    try {
      final token = await _auth.token();
      final kind = _auth.kind;
      final graphs = GraphService();
      try {
        await graphs.ensureFolder(token, kind, '00 Inbox');
        final n = _items.indexWhere((i) => i.id == item.id);
        _updateItem(
            item.id,
            (i) =>
                i.copyWith(status: CaptureStatus.uploading, clearError: true));
        final inboxName =
            inboxNameFor(_stamp, n < 0 ? 0 : n, item.isPdf ? '.pdf' : '.jpg');
        await _uploadOne(graphs, token, kind, item, inboxName);
        _updateItem(
            item.id,
            (i) => i.copyWith(
                status: CaptureStatus.uploaded,
                inboxName: inboxName,
                clearError: true));
      } finally {
        graphs.close();
      }
    } on SocketException catch (_) {
      _updateItem(
          item.id, (i) => i.copyWith(status: CaptureStatus.queued));
      if (mounted) setState(() => _offline = true);
    } catch (e) {
      _updateItem(item.id,
          (i) => i.copyWith(status: CaptureStatus.failed, error: _friendly(e)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Signed-in flow, last step: scan the inbox once. Pops a
  /// [CaptureScanSummary] when everything reads cleanly; per-file errors
  /// stay on screen with a way back instead.
  Future<void> _scanOnce() async {
    final settings = _settings;
    if (settings == null || _scanning) return;
    setState(() {
      _scanning = true;
      _error = null;
      _doneMessage = null;
      _scanErrors = const [];
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
      final fresh = outcome.proposals.length;
      final needALook = outcome.errors.length;
      await CaptureQueueStore.clear();
      if (!mounted) return;
      if (needALook == 0) {
        Navigator.of(context)
            .pop(CaptureScanSummary(fresh: fresh, needALook: 0));
      } else {
        setState(() {
          _scanning = false;
          _items = const [];
          _doneMessage =
              'Uploaded · $fresh proposal${fresh == 1 ? '' : 's'} ready';
          _scanErrors = outcome.errors;
          _summary =
              CaptureScanSummary(fresh: fresh, needALook: needALook);
        });
      }
    } on SocketException catch (_) {
      if (!mounted) return;
      setState(() {
        _scanning = false;
        _offline = true;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = _friendly(e);
        _scanning = false;
      });
    }
  }

  /// Signed-out flow: read every queued photo directly with the runtime.
  Future<void> _readAll() async {
    final settings = _settings;
    if (settings == null || _busy) return;
    final photos =
        _items.where((i) => !i.isPdf).toList(growable: false);
    setState(() {
      _busy = true;
      _error = null;
      _doneMessage = null;
      _readingTotal = photos.length;
      _readingDone = 0;
      _offline = false;
    });
    try {
      final found = <Proposal>[];
      for (final item in photos) {
        _updateItem(
            item.id,
            (i) =>
                i.copyWith(status: CaptureStatus.uploading, clearError: true));
        try {
          final staged = File(item.path);
          if (!await staged.exists()) {
            throw const FileSystemException(
                'That photo is no longer on this phone (cache cleared).');
          }
          final raw = await staged.readAsBytes();
          final bytes = await ImagePrep.preparedBytes(
            src: raw,
            quarters: item.rotationQuarters,
            crop: item.crop,
            isPdf: false,
          );
          final tmp = File('${item.path}.upload.jpg');
          await tmp.writeAsBytes(bytes, flush: true);
          try {
            final json =
                await RuntimeClient(settings).extract(tmp);
            found.add(Proposal.fromRuntime(json)
                .copyWith(localImagePath: item.path));
          } finally {
            try {
              await tmp.delete();
            } catch (_) {}
          }
          _updateItem(item.id,
              (i) => i.copyWith(status: CaptureStatus.uploaded, clearError: true));
        } on SocketException catch (_) {
          _updateItem(
              item.id, (i) => i.copyWith(status: CaptureStatus.queued));
          if (mounted) setState(() => _offline = true);
          break;
        } catch (e) {
          _updateItem(item.id,
              (i) => i.copyWith(status: CaptureStatus.failed, error: _friendly(e)));
        }
        if (mounted) setState(() => _readingDone = _readingDone + 1);
      }
      if (!mounted) return;
      if (_items.any((i) => i.isPdf)) {
        setState(() => _error =
            'PDFs need Microsoft sign-in — photos were read below.');
      }
      if (found.isNotEmpty && !_offline) {
        await CaptureQueueStore.clear();
        if (!mounted) return;
        Navigator.of(context).pop(found);
      } else if (found.isEmpty && !_offline && _error == null) {
        setState(() => _error = 'Nothing was read. Try again.');
      }
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
          _readingTotal = 0;
        });
      }
    }
  }

  /// Preview one photo: rotate and drag the corners before upload.
  Future<void> _editItem(CaptureItem item) async {
    if (item.isPdf) return;
    Uint8List? bytes;
    try {
      bytes = await File(item.path).readAsBytes();
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = 'That photo is no longer on this phone.');
      return;
    }
    if (!mounted) return;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => SafeArea(
        child: SingleChildScrollView(
          padding: EdgeInsets.only(
            left: 16,
            right: 16,
            top: 12,
            bottom: MediaQuery.of(sheetContext).viewInsets.bottom + 16,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Preview · ${item.displayName}',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              CropEditor(
                bytes: bytes!,
                quarters: item.rotationQuarters,
                crop: item.crop,
                onChanged: (quarters, crop) => _updateItem(
                  item.id,
                  (i) => i.copyWith(
                    rotationQuarters: quarters,
                    crop: crop,
                    clearCrop: crop == null,
                  ),
                ),
              ),
              const SizedBox(height: 8),
              FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size.fromHeight(48),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14)),
                ),
                onPressed: () => Navigator.of(sheetContext).pop(),
                child: const Text('Done'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final busyText = !_signedIn && _readingTotal > 0
        ? 'Reading ${_readingDone + 1} of $_readingTotal…'
        : _scanning
            ? 'Scanning your inbox…'
            : _busy
                ? 'Uploading to your 00 Inbox…'
                : '';
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          'Add receipts',
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
                      'Signed in — photos go to the 00 Inbox folder in your own OneDrive as receipt-<date>-<n>. One scan at the end reads them all.',
                      style: TextStyle(
                          color: AccnomosColors.tealDark, height: 1.4),
                    ),
                  ),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    style: FilledButton.styleFrom(
                      backgroundColor: AccnomosColors.teal,
                      minimumSize: const Size.fromHeight(56),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14)),
                    ),
                    onPressed: (_busy || _scanning) ? null : _takePhoto,
                    icon: const Icon(Icons.photo_camera_outlined),
                    label: const Text('Take a photo',
                        style: TextStyle(
                            fontWeight: FontWeight.w800, fontSize: 16)),
                  ),
                ),
                const SizedBox(height: 8),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(56),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14)),
                    ),
                    onPressed: (_busy || _scanning) ? null : _pickGallery,
                    icon: const Icon(Icons.photo_library_outlined),
                    label: const Text('Choose from gallery',
                        style: TextStyle(
                            fontWeight: FontWeight.w700, fontSize: 16)),
                  ),
                ),
                const Padding(
                  padding: EdgeInsets.only(top: 6),
                  child: Text(
                    'Add as many as you like. Photos shared from another app land here too.',
                    style: TextStyle(fontSize: 12, height: 1.4),
                  ),
                ),
                for (final item in _items) _queueCard(item),
                if (_offline) _offlineBox(),
                if (_busy || _scanning) ...[
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: AccnomosColors.tealTint,
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        LinearProgressIndicator(
                          color: AccnomosColors.tealDark,
                          backgroundColor: Colors.white,
                        ),
                        const SizedBox(height: 12),
                        Text(busyText,
                            style: const TextStyle(
                                color: AccnomosColors.tealDark,
                                fontWeight: FontWeight.w700,
                                height: 1.4)),
                      ],
                    ),
                  ),
                ],
                if (_items.isNotEmpty) ...[
                  const SizedBox(height: 12),
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
                        onPressed: (_busy ||
                                _scanning ||
                                _pendingCount == 0 ||
                                _settings == null)
                            ? null
                            : () => _uploadAll(),
                        child: Text(
                            'Upload ${_pendingCount > 0 ? _pendingCount : ''}'
                                .trim(),
                            style: const TextStyle(
                                fontWeight: FontWeight.w800, fontSize: 16)),
                      ),
                    ),
                  if (_signedIn && _uploadedCount > 0 && _pendingCount == 0)
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: SizedBox(
                        width: double.infinity,
                        child: OutlinedButton(
                          style: OutlinedButton.styleFrom(
                            minimumSize: const Size.fromHeight(52),
                            shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(14)),
                          ),
                          onPressed:
                              (_busy || _scanning) ? null : _scanOnce,
                          child: const Text('Scan now'),
                        ),
                      ),
                    ),
                  if (!_signedIn)
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        style: FilledButton.styleFrom(
                          backgroundColor: AccnomosColors.teal,
                          minimumSize: const Size.fromHeight(52),
                          shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(14)),
                        ),
                        onPressed: (_busy ||
                                _scanning ||
                                _pendingCount == 0 ||
                                _settings == null)
                            ? null
                            : _readAll,
                        child: const Text('Read with Meta AI',
                            style: TextStyle(
                                fontWeight: FontWeight.w800, fontSize: 16)),
                      ),
                    ),
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
                        if (_scanErrors.isNotEmpty)
                          for (final e in _scanErrors)
                            Padding(
                              padding: const EdgeInsets.only(top: 6),
                              child: Text('${e.path}: ${e.error}',
                                  style: const TextStyle(
                                      color: AccnomosColors.tealDark,
                                      height: 1.4)),
                            ),
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
                            onPressed: () => Navigator.of(context)
                                .pop(_summary ?? true),
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

  /// One row of the upload queue with its state and retry.
  Widget _queueCard(CaptureItem item) {
    final statusLabel = switch (item.status) {
      CaptureStatus.queued => 'Queued',
      CaptureStatus.uploading =>
        _signedIn ? 'Uploading…' : 'Reading…',
      CaptureStatus.uploaded => 'Uploaded',
      CaptureStatus.failed => 'Failed',
    };
    final statusColor = switch (item.status) {
      CaptureStatus.uploaded => AccnomosColors.tealDark,
      CaptureStatus.failed => _warnInk,
      _ => AccnomosColors.muted,
    };
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Row(
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: SizedBox(
              width: 56,
              height: 56,
              child: item.isPdf
                  ? const ColoredBox(
                      color: AccnomosColors.tealTint,
                      child: Icon(Icons.picture_as_pdf_outlined,
                          color: AccnomosColors.tealDark),
                    )
                  : Image.file(
                      File(item.path),
                      fit: BoxFit.cover,
                      errorBuilder: (_, _, _) => const ColoredBox(
                        color: AccnomosColors.tealTint,
                        child: Icon(Icons.broken_image_outlined,
                            color: AccnomosColors.tealDark),
                      ),
                    ),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  item.status == CaptureStatus.uploaded &&
                          item.inboxName != null
                      ? item.inboxName!
                      : item.displayName,
                  softWrap: false,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 2),
                Text(
                  item.status == CaptureStatus.failed &&
                          item.error != null
                      ? '${item.error}'
                      : '$statusLabel${item.edited ? ' · edited' : ''}',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                      color: statusColor, fontSize: 12, height: 1.3),
                ),
              ],
            ),
          ),
          if (item.status == CaptureStatus.uploading ||
              _busy && item.status == CaptureStatus.queued)
            const SizedBox(
              width: 48,
              height: 48,
              child: Center(
                child: SizedBox(
                  width: 20,
                  height: 20,
                  child:
                      CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
            )
          else ...[
            if (!item.isPdf)
              IconButton(
                constraints:
                    const BoxConstraints(minWidth: 48, minHeight: 48),
                icon: const Icon(Icons.tune_outlined),
                tooltip: 'Preview and crop',
                onPressed: (_busy || _scanning)
                    ? null
                    : () => _editItem(item),
              ),
            if (item.status == CaptureStatus.failed)
              IconButton(
                constraints:
                    const BoxConstraints(minWidth: 48, minHeight: 48),
                icon: const Icon(Icons.refresh_outlined),
                tooltip: 'Retry',
                onPressed: (_busy || _scanning || !_signedIn)
                    ? null
                    : () => _retryItem(item),
              ),
            IconButton(
              constraints:
                  const BoxConstraints(minWidth: 48, minHeight: 48),
              icon: const Icon(Icons.close),
              tooltip: 'Remove',
              onPressed: (_busy || _scanning)
                  ? null
                  : () => _removeItem(item),
            ),
          ],
        ],
      ),
    );
  }

  Widget _offlineBox() {
    final kept =
        _items.where((i) => i.status != CaptureStatus.uploaded).length;
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
          Text(
            'You are offline — $kept photo${kept == 1 ? '' : 's'} kept on this phone. They upload when you are back.',
            style: const TextStyle(color: _warnInk, height: 1.4),
          ),
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
              onPressed: (_busy || _scanning || !_signedIn)
                  ? null
                  : () => _uploadAll(),
              child: const Text('Try again'),
            ),
          ),
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
              onPressed: (_busy || _scanning || _pendingCount == 0)
                  ? null
                  : (_signedIn ? () => _uploadAll() : _readAll),
              child: const Text('Retry'),
            ),
          ),
        ],
      ),
    );
  }
}
