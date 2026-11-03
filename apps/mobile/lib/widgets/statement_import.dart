import 'package:flutter/material.dart';

import '../services/file_picker.dart';
import '../services/runtime_client.dart';
import '../theme.dart';

/// What one import did, in words: "Imported 42 lines (40 new) from
/// statement.csv." or "That statement was already imported."
String statementImportResult(Map<String, dynamic> r, String name) {
  if (r['duplicate_file'] == true) return 'That statement was already imported — nothing changed.';
  final lines = r['lines'] is num ? (r['lines'] as num).toInt() : 0;
  final fresh = r['new_lines'] is num ? (r['new_lines'] as num).toInt() : 0;
  final feed = r['from_feed'] is num ? (r['from_feed'] as num).toInt() : 0;
  final parts = ['Imported $lines ${lines == 1 ? 'line' : 'lines'} ($fresh new) from $name.'];
  if (feed > 0) parts.add('$feed ${feed == 1 ? 'line was' : 'lines were'} already in from your bank feed.');
  return parts.join(' ');
}

/// Pick a bank statement CSV with the phone's file picker and import it
/// through `POST /books/bank/import`, as the web's Bank › Upload does.
/// Returns the sentence to show, or null when the user backed out.
Future<String?> pickAndImportStatement(
  RuntimeClient client, {
  FilePicker? picker,
}) async {
  final file = await (picker ?? FilePicker()).pick(mimeTypes: FilePicker.statementTypes);
  if (file == null) return null;
  if (!file.name.toLowerCase().endsWith('.csv')) {
    return 'Pick the statement as a CSV file (most banks offer "Download as CSV").';
  }
  final r = await client.bankImportBytes(file.name, file.bytes);
  return statementImportResult(r, file.name);
}

/// A button that runs [pickAndImportStatement] with [clientFor] and shows the
/// outcome under itself; [onImported] runs after a successful import.
class ImportStatementButton extends StatefulWidget {
  const ImportStatementButton({
    super.key,
    required this.clientFor,
    this.onImported,
    this.label = 'Import a bank statement (CSV)',
    this.picker,
  });

  final Future<RuntimeClient> Function() clientFor;
  final VoidCallback? onImported;
  final String label;
  final FilePicker? picker;

  @override
  State<ImportStatementButton> createState() => _ImportStatementButtonState();
}

class _ImportStatementButtonState extends State<ImportStatementButton> {
  bool _busy = false;
  String? _note;

  Future<void> _run() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _note = null;
    });
    try {
      final client = await widget.clientFor();
      final note = await pickAndImportStatement(client, picker: widget.picker);
      if (!mounted) return;
      setState(() => _note = note);
      if (note != null && !note.startsWith('Pick the statement')) widget.onImported?.call();
    } catch (e) {
      if (!mounted) return;
      setState(() => _note = e is RuntimeException || e is FilePickerException ? '$e' : 'Could not import that statement. $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        FilledButton.icon(
          key: const Key('import-statement'),
          style: FilledButton.styleFrom(
            backgroundColor: AccnomosColors.teal,
            minimumSize: const Size.fromHeight(48),
          ),
          icon: _busy
              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Icon(Icons.upload_file_outlined),
          label: Text(_busy ? 'Importing…' : widget.label),
          onPressed: _busy ? null : _run,
        ),
        if (_note != null) ...[
          const SizedBox(height: 6),
          Semantics(
            liveRegion: true,
            child: Text(_note!,
                key: const Key('import-statement-note'),
                style: const TextStyle(color: AccnomosColors.tealDark, height: 1.4)),
          ),
        ],
      ],
    );
  }
}
