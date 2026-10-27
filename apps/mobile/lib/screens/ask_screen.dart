import 'package:flutter/material.dart';

import '../theme.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);

/// Ask your books a question, by text or voice.
///
/// Voice input and live answers arrive in a later update; this screen
/// shows a sample conversation.
class AskScreen extends StatefulWidget {
  const AskScreen({super.key});

  @override
  State<AskScreen> createState() => _AskScreenState();
}

class _AskScreenState extends State<AskScreen> {
  final TextEditingController _input = TextEditingController();

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          'Ask',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
      ),
      body: Column(
        children: [
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _userBubble(),
                const SizedBox(height: 12),
                _answerCard(),
              ],
            ),
          ),
          _inputRow(),
        ],
      ),
    );
  }

  Widget _userBubble() {
    return Align(
      alignment: Alignment.centerRight,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 320),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            const Text(
              'Spoken · Muse Voice',
              style: TextStyle(
                fontSize: 11,
                color: AccnomosColors.muted,
              ),
            ),
            const SizedBox(height: 4),
            Container(
              padding: const EdgeInsets.symmetric(
                horizontal: 14,
                vertical: 12,
              ),
              decoration: BoxDecoration(
                color: AccnomosColors.teal,
                borderRadius: BorderRadius.circular(16),
              ),
              child: const Text(
                'Why is my VAT higher than last quarter?',
                style: TextStyle(color: Colors.white, height: 1.4),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _numbered(String number, String text) {
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 20,
            child: Text(
              '$number.',
              style: const TextStyle(
                color: AccnomosColors.ink,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                color: AccnomosColors.ink,
                height: 1.4,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _answerCard() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Your Q3 bill is £2,140, up £620 on Q2. Two reasons:',
            style: TextStyle(
              color: AccnomosColors.ink,
              fontWeight: FontWeight.w700,
              height: 1.4,
            ),
          ),
          _numbered(
            '1',
            'Sales were £6,400 higher — the Hartley kitchen job (INV-0039, INV-0041).',
          ),
          _numbered(
            '2',
            'You reclaimed less: the Howdens invoice (£412 VAT) is still '
                'waiting for a VAT number, so it\'s not in Box 4 yet.',
          ),
          Container(
            width: double.infinity,
            margin: const EdgeInsets.only(top: 10),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: _warnBg,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: _warnBorder),
            ),
            child: const Text(
              'If Howdens sends the VAT invoice before 7 Nov, your bill '
                  'drops to about £1,728.',
              style: TextStyle(color: _warnInk, height: 1.4),
            ),
          ),
          const SizedBox(height: 10),
          const Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              Chip(
                label: Text(
                  '05 VAT returns/2026-Q3/return.json',
                  style: TextStyle(fontSize: 12),
                ),
              ),
              Chip(
                label: Text(
                  'Books.xlsx · VAT',
                  style: TextStyle(fontSize: 12),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
            'Numbers by code · explanation by Muse Spark · read aloud by your phone',
            style: TextStyle(
              fontSize: 12,
              color: AccnomosColors.muted,
            ),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              ActionChip(
                label: const Text('Chase Howdens for the invoice'),
                onPressed: () => setState(
                  () => _input.text = 'Chase Howdens for the invoice',
                ),
              ),
              ActionChip(
                label: const Text('Show Box 4 entries'),
                onPressed: () =>
                    setState(() => _input.text = 'Show Box 4 entries'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _inputRow() {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: Color(0xFFE3E1D8))),
      ),
      child: SafeArea(
        top: false,
        child: Row(
          children: [
            Expanded(
              child: SizedBox(
                height: 56,
                child: TextField(
                  controller: _input,
                  decoration: InputDecoration(
                    hintText: 'Ask or say something…',
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 16,
                    ),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(28),
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 8),
            SizedBox(
              width: 56,
              height: 56,
              child: FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  padding: EdgeInsets.zero,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(28),
                  ),
                ),
                onPressed: () => ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('Voice arrives in the next update.'),
                  ),
                ),
                child: const Icon(Icons.mic, color: Colors.white),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
