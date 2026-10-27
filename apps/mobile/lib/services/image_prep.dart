import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'capture_queue.dart';

/// Applies the preview edits (rotation, corner crop) to the uploaded bytes.
///
/// Pure Dart, no packages: the pixels go through `dart:ui`, the PNG bytes
/// come out of the tiny encoder below. PDFs pass through untouched — only
/// photos can be cropped or rotated.
///
/// The crop rectangle lives in original-image coordinates; it is cut first
/// and the result is then turned clockwise by [quarters].
class ImagePrep {
  /// Returns the bytes to upload for [src].
  ///
  /// Returns [src] unchanged when there is nothing to apply (no rotation,
  /// no crop, or a PDF), keeping the original encoding.
  static Future<Uint8List> preparedBytes({
    required Uint8List src,
    required int quarters,
    CropRect? crop,
    required bool isPdf,
  }) async {
    final turns = quarters % 4;
    if (isPdf || (turns == 0 && (crop == null || crop.isFull))) {
      return src;
    }
    final image = await _decode(src);
    try {
      final pixels =
          (crop == null || crop.isFull) ? null : crop.toPixels(image.width, image.height);
      final cutW = pixels?.width ?? image.width;
      final cutH = pixels?.height ?? image.height;
      final odd = turns % 2 == 1;
      final outW = odd ? cutH : cutW;
      final outH = odd ? cutW : cutH;

      final recorder = ui.PictureRecorder();
      final canvas = ui.Canvas(recorder);
      canvas.translate(outW / 2, outH / 2);
      canvas.rotate(turns * math.pi / 2);
      final srcRect = pixels == null
          ? ui.Rect.fromLTWH(
              0, 0, image.width.toDouble(), image.height.toDouble())
          : ui.Rect.fromLTWH(pixels.x.toDouble(), pixels.y.toDouble(),
              pixels.width.toDouble(), pixels.height.toDouble());
      canvas.drawImageRect(
        image,
        srcRect,
        ui.Rect.fromCenter(
          center: ui.Offset.zero,
          width: cutW.toDouble(),
          height: cutH.toDouble(),
        ),
        ui.Paint()..filterQuality = ui.FilterQuality.high,
      );
      final out =
          await recorder.endRecording().toImage(outW, outH);
      try {
        final rgba = await out.toByteData(format: ui.ImageByteFormat.rawRgba);
        if (rgba == null) return src;
        return PngEncoder.encodeRgba(
          rgba.buffer.asUint8List(),
          outW,
          outH,
        );
      } finally {
        out.dispose();
      }
    } finally {
      image.dispose();
    }
  }

  static Future<ui.Image> _decode(Uint8List src) async {
    final codec = await ui.instantiateImageCodec(src);
    try {
      final frame = await codec.getNextFrame();
      return frame.image;
    } finally {
      codec.dispose();
    }
  }
}

/// Minimal PNG encoder (8-bit RGBA, non-interlaced) on `dart:convert` only.
class PngEncoder {
  static const _signature = [
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
  ];

  static final List<int> _crcTable = _buildCrcTable();

  static List<int> _buildCrcTable() {
    final table = List<int>.filled(256, 0);
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) {
        c = (c & 1) != 0 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
      }
      table[n] = c;
    }
    return table;
  }

  static int crc32(List<int> bytes) {
    var crc = 0xFFFFFFFF;
    for (final b in bytes) {
      crc = _crcTable[(crc ^ b) & 0xFF] ^ (crc >>> 8);
    }
    return crc ^ 0xFFFFFFFF;
  }

  static void _chunk(BytesBuilder out, String type, List<int> data) {
    final typeBytes = ascii.encode(type);
    final length = ByteData(4)..setUint32(0, data.length);
    out.add(length.buffer.asUint8List());
    out.add(typeBytes);
    out.add(data);
    final crc = ByteData(4)..setUint32(0, crc32([...typeBytes, ...data]));
    out.add(crc.buffer.asUint8List());
  }

  /// Encodes row-major [rgba] ([width]×[height], 4 bytes a pixel).
  static Uint8List encodeRgba(Uint8List rgba, int width, int height) {
    assert(rgba.length == width * height * 4);
    final out = BytesBuilder();
    out.add(_signature);
    final ihdr = ByteData(13)
      ..setUint32(0, width)
      ..setUint32(4, height)
      ..setUint8(8, 8) // bit depth
      ..setUint8(9, 6) // colour type: truecolour with alpha
      ..setUint8(10, 0)
      ..setUint8(11, 0)
      ..setUint8(12, 0);
    _chunk(out, 'IHDR', ihdr.buffer.asUint8List());
    final raw = BytesBuilder();
    final rowBytes = width * 4;
    for (var y = 0; y < height; y++) {
      raw.addByte(0); // filter type 0 (none)
      raw.add(rgba.sublist(y * rowBytes, (y + 1) * rowBytes));
    }
    _chunk(out, 'IDAT', zlib.encode(raw.toBytes()));
    _chunk(out, 'IEND', const []);
    return out.toBytes();
  }

  /// Reads back the dimensions from bytes this encoder wrote.
  static (int, int)? probeDimensions(Uint8List png) {
    if (png.length < 33) return null;
    for (var i = 0; i < _signature.length; i++) {
      if (png[i] != _signature[i]) return null;
    }
    final data = ByteData.sublistView(png);
    if (ascii.decode(png.sublist(12, 16)) != 'IHDR') return null;
    return (data.getUint32(16), data.getUint32(20));
  }
}
