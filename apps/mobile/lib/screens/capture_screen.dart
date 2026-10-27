import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../models/proposal.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);

/// Photograph or pick a receipt, read it with Meta AI, and hand the
/// resulting [Proposal] back to the review list.
class CaptureScreen extends StatefulWidget {
  const CaptureScreen({super.key});

  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends State<CaptureScreen> {
  final ImagePicker _picker = ImagePicker();
  AppSettings? _settings;
  XFile? _photo;
  bool _reading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    AppSettings.load().then((settings) {
      if (mounted) setState(() => _settings = settings);
    });
  }

  bool get _localMode => _settings == null || _settings!.aiMode != 'key';

  String _friendly(Object e) => e.toString().replaceFirst('Exception: ', '');

  Future<void> _pick(ImageSource source) async {
    try {
      final file = await _picker.pickImage(source: source);
      if (file == null || !mounted) return;
      setState(() {
        _photo = file;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    }
  }

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

  @override
  Widget build(BuildContext context) {
    final progressText = _localMode
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
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
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
                    style:
                        TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
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
                    style:
                        TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
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
                      }),
              child: const Text('Choose a different photo'),
            ),
            const SizedBox(height: 4),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size.fromHeight(52),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14)),
                ),
                onPressed: (_reading || _settings == null) ? null : _read,
                child: const Text('Read with Meta AI',
                    style:
                        TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
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
              onPressed: (_photo == null || _reading) ? null : _read,
              child: const Text('Retry'),
            ),
          ),
        ],
      ),
    );
  }
}
