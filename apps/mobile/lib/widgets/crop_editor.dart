import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../services/capture_queue.dart';

/// Preview an image before upload: turn it and drag the corners to crop.
///
/// Pure Flutter, no packages. The crop rectangle is normalised (0..1) in the
/// *original* image's coordinates; turning the image turns the rectangle
/// with it ([CropRect.quarterTurn]) so the selection keeps its content.
///
/// Lay out for a 360 dp phone: the preview box is square-ish and every
/// control is a 48 dp touch target.
class CropEditor extends StatefulWidget {
  const CropEditor({
    super.key,
    required this.bytes,
    this.quarters = 0,
    this.crop,
    this.onChanged,
  });

  /// Raw image bytes for the preview.
  final Uint8List bytes;

  /// Clockwise quarter turns already applied.
  final int quarters;

  /// Current crop in original-image coordinates; null means the full frame.
  final CropRect? crop;

  final void Function(int quarters, CropRect? crop)? onChanged;

  @override
  State<CropEditor> createState() => _CropEditorState();
}

class _CropEditorState extends State<CropEditor> {
  late int _quarters;
  CropRect? _crop;

  @override
  void initState() {
    super.initState();
    _quarters = widget.quarters % 4;
    _crop = widget.crop;
  }

  /// The crop as drawn on screen: turned with the image.
  CropRect get _drawn {
    var rect = _crop ?? CropRect.full();
    for (var i = 0; i < _quarters; i++) {
      rect = rect.quarterTurn();
    }
    return rect;
  }

  void _emit() => widget.onChanged?.call(_quarters, _crop);

  void _turn() {
    setState(() {
      _quarters = (_quarters + 1) % 4;
      if (_crop != null) _crop = _crop!.quarterTurn();
    });
    _emit();
  }

  void _reset() {
    setState(() {
      _quarters = 0;
      _crop = null;
    });
    _emit();
  }

  /// Move one drawn corner to [at] (fractional box coordinates).
  void _dragCorner(_Corner corner, Offset at) {
    final drawn = _drawn;
    var rect = switch (corner) {
      _Corner.topLeft => CropRect(
          left: at.dx, top: at.dy, right: drawn.right, bottom: drawn.bottom),
      _Corner.topRight => CropRect(
          left: drawn.left, top: at.dy, right: at.dx, bottom: drawn.bottom),
      _Corner.bottomLeft => CropRect(
          left: at.dx, top: drawn.top, right: drawn.right, bottom: at.dy),
      _Corner.bottomRight => CropRect(
          left: drawn.left, top: drawn.top, right: at.dx, bottom: at.dy),
    }
        .normalised();
    // Keep a usable minimum size so the handles cannot cross over.
    const min = 0.05;
    if (rect.right - rect.left < min || rect.bottom - rect.top < min) return;
    // Map the drawn rectangle back to original-image coordinates: the
    // inverse of the image's turns, i.e. (4 − quarters) clockwise turns.
    for (var i = 0; i < (4 - _quarters) % 4; i++) {
      rect = rect.quarterTurn();
    }
    setState(() => _crop = rect.isFull ? null : rect);
    _emit();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        AspectRatio(
          aspectRatio: 1,
          child: LayoutBuilder(
            builder: (context, constraints) {
              final size =
                  Size(constraints.maxWidth, constraints.maxHeight);
              return _CropBox(
                bytes: widget.bytes,
                quarters: _quarters,
                crop: _drawn,
                size: size,
                onDragCorner: _dragCorner,
              );
            },
          ),
        ),
        const SizedBox(height: 4),
        Wrap(
          spacing: 4,
          children: [
            TextButton.icon(
              style: TextButton.styleFrom(
                  minimumSize: const Size(48, 48)),
              onPressed: _turn,
              icon: const Icon(Icons.rotate_90_degrees_cw),
              label: const Text('Rotate'),
            ),
            TextButton.icon(
              style: TextButton.styleFrom(
                  minimumSize: const Size(48, 48)),
              onPressed: _reset,
              icon: const Icon(Icons.crop_free),
              label: const Text('Full frame'),
            ),
          ],
        ),
        const Text(
          'Only this area is uploaded. The reader also crops with SAM when available.',
          style: TextStyle(fontSize: 12, height: 1.4),
        ),
      ],
    );
  }
}

enum _Corner { topLeft, topRight, bottomLeft, bottomRight }

/// The preview image with the crop overlay and four drag handles.
class _CropBox extends StatelessWidget {
  const _CropBox({
    required this.bytes,
    required this.quarters,
    required this.crop,
    required this.size,
    required this.onDragCorner,
  });

  final Uint8List bytes;
  final int quarters;
  final CropRect crop;
  final Size size;
  final void Function(_Corner corner, Offset at) onDragCorner;

  Offset _cornerOffset(_Corner corner) {
    final x = (corner == _Corner.topLeft || corner == _Corner.bottomLeft)
        ? crop.left
        : crop.right;
    final y = (corner == _Corner.topLeft || corner == _Corner.topRight)
        ? crop.top
        : crop.bottom;
    return Offset(x * size.width, y * size.height);
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.black12,
      child: Stack(
        children: [
          Positioned.fill(
            child: RotatedBox(
              quarterTurns: quarters,
              child: Image.memory(bytes, fit: BoxFit.contain),
            ),
          ),
          Positioned.fill(
            child: CustomPaint(painter: _CropPainter(crop: crop)),
          ),
          for (final corner in _Corner.values)
            Positioned(
              left: _cornerOffset(corner).dx - 24,
              top: _cornerOffset(corner).dy - 24,
              child: GestureDetector(
                key: ValueKey('crop-handle-${corner.name}'),
                behavior: HitTestBehavior.opaque,
                onPanUpdate: (details) {
                  final box =
                      context.findRenderObject() as RenderBox?;
                  if (box == null) return;
                  final local =
                      box.globalToLocal(details.globalPosition);
                  onDragCorner(
                    corner,
                    Offset(
                      (local.dx / box.size.width).clamp(0.0, 1.0),
                      (local.dy / box.size.height).clamp(0.0, 1.0),
                    ),
                  );
                },
                child: SizedBox(
                  width: 48,
                  height: 48,
                  child: Center(
                    child: Container(
                      width: 20,
                      height: 20,
                      decoration: BoxDecoration(
                        color: Colors.white,
                        border: Border.all(
                            color: Colors.teal.shade700, width: 3),
                        borderRadius: BorderRadius.circular(6),
                      ),
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// Dims the cropped-away area and outlines the kept rectangle.
class _CropPainter extends CustomPainter {
  const _CropPainter({required this.crop});

  final CropRect crop;

  @override
  void paint(Canvas canvas, Size size) {
    final kept = Rect.fromLTRB(
      crop.left * size.width,
      crop.top * size.height,
      crop.right * size.width,
      crop.bottom * size.height,
    );
    canvas.saveLayer(
      Offset.zero & size,
      Paint()..color = Colors.black54,
    );
    canvas.drawRect(Offset.zero & size, Paint());
    canvas.drawRect(kept, Paint()..blendMode = BlendMode.clear);
    canvas.restore();
    canvas.drawRect(
      kept,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..color = Colors.teal.shade700,
    );
  }

  @override
  bool shouldRepaint(_CropPainter old) => old.crop != crop;
}
