import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../models/proposal.dart';

/// Drawn receipt used when the phone holds no photo for a card (the
/// signed-out samples and live cards whose document cannot be fetched).
/// Fixed logical size so the crop toggle can cut the same region the
/// runtime read.
class _ReceiptPaper extends StatelessWidget {
  const _ReceiptPaper();

  static const Size logicalSize = Size(300, 400);

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.white,
      padding: const EdgeInsets.fromLTRB(24, 28, 24, 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(height: 22, width: 150, color: const Color(0xFF1F2937)),
          const SizedBox(height: 8),
          Container(height: 10, width: 110, color: const Color(0xFFD1D5DB)),
          const SizedBox(height: 20),
          for (var i = 0; i < 5; i++) ...[
            Row(
              children: [
                Expanded(
                  flex: 3,
                  child: Container(height: 10, color: const Color(0xFFE5E7EB)),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Container(height: 10, color: const Color(0xFFE5E7EB)),
                ),
              ],
            ),
            const SizedBox(height: 10),
          ],
          const Spacer(),
          Container(height: 2, color: const Color(0xFF1F2937)),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: Container(height: 14, color: const Color(0xFF1F2937)),
              ),
              const SizedBox(width: 12),
              Container(height: 14, width: 64, color: const Color(0xFF1F2937)),
            ],
          ),
        ],
      ),
    );
  }
}

/// The drawn receipt scaled to exactly [width]×[height], so it never
/// overflows a small thumbnail or a fitted crop.
Widget _scaledPaper(double width, double height) {
  return SizedBox(
    width: width,
    height: height,
    child: const FittedBox(
      fit: BoxFit.fill,
      child: SizedBox(
        width: 300,
        height: 400,
        child: _ReceiptPaper(),
      ),
    ),
  );
}

bool _isPdf(Uint8List bytes) {
  return bytes.length > 4 &&
      bytes[0] == 0x25 &&
      bytes[1] == 0x50 &&
      bytes[2] == 0x44 &&
      bytes[3] == 0x46;
}

/// Tappable document thumbnail for a review card header (72×92, like the
/// web card's media). Shows the captured photo when the phone holds one,
/// else the drawn receipt; a 'Cropped' badge marks cards the reader cut.
class ProposalThumbnail extends StatelessWidget {
  const ProposalThumbnail({
    super.key,
    required this.proposal,
    required this.onTap,
  });

  final Proposal proposal;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final path = proposal.localImagePath;
    final isPdf = path != null && path.toLowerCase().endsWith('.pdf');
    return Semantics(
      button: true,
      label: 'Open the document for ${proposal.supplier}',
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          width: 72,
          height: 92,
          clipBehavior: Clip.antiAlias,
          decoration: BoxDecoration(
            color: const Color(0xFFE0E0E0),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Stack(
            fit: StackFit.expand,
            children: [
              if (path != null && !isPdf)
                Image.file(
                  File(path),
                  fit: BoxFit.cover,
                  errorBuilder: (_, _, _) => _scaledPaper(72, 92),
                )
              else if (isPdf)
                const Center(
                  child: Text(
                    'PDF',
                    style: TextStyle(fontWeight: FontWeight.w800),
                  ),
                )
              else
                _scaledPaper(72, 92),
              if (proposal.cropMethod != 'none')
                const Positioned(
                  left: 4,
                  bottom: 4,
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      color: Color(0xE6FFFFFF),
                      borderRadius:
                          BorderRadius.all(Radius.circular(999)),
                    ),
                    child: Padding(
                      padding:
                          EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                      child: Text(
                        'Cropped',
                        style: TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.w800,
                          color: Color(0xFF0B5E5E),
                        ),
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Open the full-screen document viewer for [proposal]. [remoteBytes]
/// fetches the filed document (signed-in OneDrive copies); null leaves
/// the captured photo or the drawn receipt.
Future<void> showReviewImage(
  BuildContext context, {
  required Proposal proposal,
  Future<Uint8List> Function()? remoteBytes,
}) {
  return Navigator.of(context).push(
    MaterialPageRoute(
      fullscreenDialog: true,
      builder: (_) =>
          _ReviewImagePage(proposal: proposal, remoteBytes: remoteBytes),
    ),
  );
}

class _ReviewImagePage extends StatefulWidget {
  const _ReviewImagePage({required this.proposal, this.remoteBytes});

  final Proposal proposal;
  final Future<Uint8List> Function()? remoteBytes;

  @override
  State<_ReviewImagePage> createState() => _ReviewImagePageState();
}

class _ReviewImagePageState extends State<_ReviewImagePage> {
  final TransformationController _transform = TransformationController();
  bool _cropMode = false;
  bool _zoomed = false;

  bool get _hasCrop =>
      widget.proposal.cropMethod != 'none' &&
      widget.proposal.cropBox != null;

  @override
  void initState() {
    super.initState();
    _transform.addListener(_trackZoom);
  }

  @override
  void dispose() {
    _transform.removeListener(_trackZoom);
    _transform.dispose();
    super.dispose();
  }

  void _trackZoom() {
    final zoomed = !_transform.value.isIdentity();
    if (zoomed != _zoomed) setState(() => _zoomed = zoomed);
  }

  @override
  Widget build(BuildContext context) {
    final proposal = widget.proposal;
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
        title: Text(
          proposal.supplier,
          style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
        ),
        actions: [
          TextButton(
            style: TextButton.styleFrom(
              foregroundColor: Colors.white,
              minimumSize: const Size(48, 48),
            ),
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Close'),
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            if (_hasCrop)
              Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: SegmentedButton<bool>(
                  style: SegmentedButton.styleFrom(
                    foregroundColor: Colors.white,
                    selectedForegroundColor: Colors.black,
                    selectedBackgroundColor: Colors.white,
                  ),
                  segments: const [
                    ButtonSegment(value: false, label: Text('Original')),
                    ButtonSegment(value: true, label: Text('Crop')),
                  ],
                  selected: {_cropMode},
                  onSelectionChanged: (selected) =>
                      setState(() => _cropMode = selected.first),
                ),
              ),
            Expanded(child: _body()),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
              child: Text(
                _caption(),
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.white70, fontSize: 12),
              ),
            ),
          ],
        ),
      ),
    );
  }

  String _caption() {
    final note = widget.proposal.cropNote;
    if (_hasCrop) {
      final what = (note == null || note.isEmpty) ? 'Cropped' : note;
      return _cropMode
          ? '$what. The reading and the checks used this part. Pinch to zoom; swipe down to close.'
          : 'The file as it arrived. Pinch to zoom; swipe down to close.';
    }
    return 'Read as it arrived: not cropped. Pinch to zoom; swipe down to close.';
  }

  Widget _body() {
    final path = widget.proposal.localImagePath;
    if (path != null && !path.toLowerCase().endsWith('.pdf')) {
      return _viewer(_FileDoc(path));
    }
    if (path != null) return _pdfNote();
    if (widget.remoteBytes != null) {
      return FutureBuilder<Uint8List>(
        future: widget.remoteBytes!(),
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(
              child: CircularProgressIndicator(color: Colors.white),
            );
          }
          final bytes = snapshot.data;
          if (bytes == null) {
            return const _ViewerMessage(text: 'Preview unavailable.');
          }
          if (_isPdf(bytes)) return _pdfNote();
          return _viewer(_MemoryDoc(bytes));
        },
      );
    }
    return _viewer(const _PaperDoc());
  }

  Widget _pdfNote() {
    return const _ViewerMessage(
      text: 'This is a PDF — preview is not on this phone yet.',
    );
  }

  /// Swipe down closes, but only at resting zoom so panning never
  /// dismisses the viewer by accident.
  Widget _viewer(_Doc doc) {
    return Dismissible(
      key: const ValueKey('review-image'),
      direction: _zoomed ? DismissDirection.none : DismissDirection.down,
      onDismissed: (_) => Navigator.of(context).pop(),
      child: Container(
        width: double.infinity,
        height: double.infinity,
        color: Colors.black,
        child: InteractiveViewer(
          transformationController: _transform,
          minScale: 1,
          maxScale: 5,
          child: _DocView(
            doc: doc,
            cropMode: _cropMode && _hasCrop,
            cropBox: widget.proposal.cropBox,
          ),
        ),
      ),
    );
  }
}

class _ViewerMessage extends StatelessWidget {
  const _ViewerMessage({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Text(
          text,
          textAlign: TextAlign.center,
          style: const TextStyle(color: Colors.white70, fontSize: 15),
        ),
      ),
    );
  }
}

/// A document at its natural size: full-page painting plus size.
abstract class _Doc {
  const _Doc();
  Future<Size> get naturalSize;
  Widget paint(double width, double height);
}

class _PaperDoc extends _Doc {
  const _PaperDoc();
  @override
  Future<Size> get naturalSize async => _ReceiptPaper.logicalSize;
  @override
  Widget paint(double width, double height) => _scaledPaper(width, height);
}

class _FileDoc extends _Doc {
  const _FileDoc(this.path);
  final String path;
  @override
  Future<Size> get naturalSize async {
    try {
      final bytes = await File(path).readAsBytes();
      return await _rasterSize(MemoryImage(bytes));
    } catch (_) {
      return _ReceiptPaper.logicalSize;
    }
  }
  @override
  Widget paint(double width, double height) => Image.file(
        File(path),
        width: width,
        height: height,
        fit: BoxFit.fill,
        errorBuilder: (_, _, _) => _scaledPaper(width, height),
      );
}

class _MemoryDoc extends _Doc {
  const _MemoryDoc(this.bytes);
  final Uint8List bytes;
  @override
  Future<Size> get naturalSize => _rasterSize(MemoryImage(bytes));
  @override
  Widget paint(double width, double height) => Image.memory(
        bytes,
        width: width,
        height: height,
        fit: BoxFit.fill,
        errorBuilder: (_, _, _) => _scaledPaper(width, height),
      );
}

Future<Size> _rasterSize(ImageProvider provider) {
  final completer = Completer<Size>();
  final stream = provider.resolve(const ImageConfiguration());
  late final ImageStreamListener listener;
  listener = ImageStreamListener(
    (info, _) {
      stream.removeListener(listener);
      completer.complete(Size(
        info.image.width.toDouble(),
        info.image.height.toDouble(),
      ));
    },
    onError: (Object _, StackTrace? _) {
      stream.removeListener(listener);
      completer.complete(_ReceiptPaper.logicalSize);
    },
  );
  stream.addListener(listener);
  return completer.future;
}

/// Fits the original or the crop region into the viewport.
class _DocView extends StatelessWidget {
  const _DocView({required this.doc, required this.cropMode, this.cropBox});

  final _Doc doc;
  final bool cropMode;
  final List<double>? cropBox;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Size>(
      future: doc.naturalSize,
      builder: (context, snapshot) {
        if (!snapshot.hasData) {
          return const Center(
            child: CircularProgressIndicator(color: Colors.white),
          );
        }
        final natural = snapshot.data!;
        return LayoutBuilder(
          builder: (context, constraints) {
            final box = cropBox;
            final target = cropMode && box != null
                ? Size(box[2] - box[0], box[3] - box[1])
                : natural;
            final scale = (constraints.maxWidth / target.width)
                .clamp(0.05, 1.0)
                .toDouble();
            final w = target.width * scale;
            final h = target.height * scale;
            return Center(
              child: SizedBox(
                width: w,
                height: h,
                child: cropMode && box != null
                    ? ClipRect(
                        child: Stack(
                          clipBehavior: Clip.hardEdge,
                          children: [
                            Positioned(
                              left: -box[0] * scale,
                              top: -box[1] * scale,
                              child: doc.paint(
                                natural.width * scale,
                                natural.height * scale,
                              ),
                            ),
                          ],
                        ),
                      )
                    : doc.paint(w, h),
              ),
            );
          },
        );
      },
    );
  }
}
