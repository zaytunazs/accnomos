import 'package:flutter/services.dart';

/// One file the user picked with the system document picker.
class PickedFile {
  const PickedFile(this.name, this.bytes);
  final String name;
  final Uint8List bytes;
}

/// The system document picker through `accnomos/files` (MainActivity's
/// FilePickerBridge.kt): no storage permission, one file, at most 6 MB.
class FilePicker {
  FilePicker({MethodChannel? channel})
      : channel = channel ?? const MethodChannel('accnomos/files');

  final MethodChannel channel;

  /// Bank statements: CSVs, or a statement PDF with a text layer (the
  /// formats the runtime reads, services/runtime/app/bank_pdf.py).
  static const statementTypes = [
    'application/pdf',
    'text/csv',
    'text/comma-separated-values',
    'application/csv',
    'application/vnd.ms-excel',
    'text/plain',
  ];

  /// Null when the user backed out. Throws [FilePickerException] with a
  /// plain message when the file cannot be read.
  Future<PickedFile?> pick({List<String> mimeTypes = const ['*/*']}) async {
    try {
      final raw = await channel
          .invokeMapMethod<String, dynamic>('pickFile', {'mimeTypes': mimeTypes});
      if (raw == null) return null;
      final bytes = raw['bytes'];
      if (bytes is! Uint8List) return null;
      return PickedFile((raw['name'] ?? 'file').toString(), bytes);
    } on PlatformException catch (e) {
      throw FilePickerException(e.message ?? 'Could not open that file.');
    } on MissingPluginException {
      throw const FilePickerException('Picking files is not available here.');
    }
  }
}

class FilePickerException implements Exception {
  const FilePickerException(this.message);
  final String message;
  @override
  String toString() => message;
}
