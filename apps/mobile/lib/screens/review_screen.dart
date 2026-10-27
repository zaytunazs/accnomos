import 'package:flutter/material.dart';

import '../models/proposal.dart';
import '../theme.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);

String _gbp(double value) => '£${value.toStringAsFixed(2)}';

/// Review queue: a swipeable card per proposed entry.
///
/// Approve and Reject move to the next card. The camera action is a
/// placeholder until capture lands in a later update.
class ReviewScreen extends StatefulWidget {
  const ReviewScreen({super.key});

  @override
  State<ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends State<ReviewScreen> {
  final PageController _pages = PageController();
  int _index = 0;
  final Map<String, bool> _alwaysDo = {};

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  void _say(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }

  void _advance() {
    if (_index < Proposal.samples.length - 1) {
      _pages.nextPage(
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    }
  }

  void _approve() {
    _say('Approved · posted to your books');
    _advance();
  }

  void _reject() {
    _say('Rejected');
    _advance();
  }

  @override
  Widget build(BuildContext context) {
    final proposals = Proposal.samples;
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          'Review ${_index + 1} of ${proposals.length}',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.photo_camera_outlined),
            tooltip: 'Photograph a receipt',
            constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
            onPressed: () =>
                _say('Camera capture arrives in the next update.'),
          ),
        ],
      ),
      body: PageView.builder(
        controller: _pages,
        itemCount: proposals.length,
        onPageChanged: (i) => setState(() => _index = i),
        itemBuilder: (context, i) {
          final proposal = proposals[i];
          switch (proposal.status) {
            case ProposalStatus.needsALook:
              return _needsALookCard(proposal);
            case ProposalStatus.voiceNote:
              return _voiceCard(proposal);
            case ProposalStatus.proposed:
              return _proposedCard(proposal);
          }
        },
      ),
    );
  }

  Widget _header(Proposal proposal, {Color ink = AccnomosColors.ink}) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 72,
          height: 92,
          decoration: BoxDecoration(
            color: const Color(0xFFE0E0E0),
            borderRadius: BorderRadius.circular(8),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                proposal.supplier,
                style: TextStyle(
                  fontSize: 19,
                  fontWeight: FontWeight.w700,
                  color: ink,
                ),
              ),
              Text(
                _gbp(proposal.total),
                style: TextStyle(
                  fontSize: 26,
                  fontWeight: FontWeight.w800,
                  color: ink,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                '${proposal.date} · ${proposal.paidBy}',
                style: const TextStyle(color: AccnomosColors.muted),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _pill(String label, {required Color bg, required Color fg}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: fg,
          fontSize: 12,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }

  Widget _fieldRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: const TextStyle(color: AccnomosColors.muted),
            ),
          ),
          Text(
            value,
            style: const TextStyle(
              color: AccnomosColors.ink,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }

  Widget _noteBox(String text, {required Color bg, required Color fg}) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(text, style: TextStyle(color: fg, height: 1.4)),
    );
  }

  Widget _alwaysRow(Proposal proposal) {
    return Row(
      children: [
        Checkbox(
          value: _alwaysDo[proposal.id] ?? false,
          activeColor: AccnomosColors.teal,
          onChanged: (v) =>
              setState(() => _alwaysDo[proposal.id] = v ?? false),
        ),
        Expanded(
          child: Text('Always do this for ${proposal.supplier}'),
        ),
      ],
    );
  }

  Widget _decisionRow() {
    final buttonShape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(14),
    );
    return Row(
      children: [
        Expanded(
          flex: 2,
          child: FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: AccnomosColors.teal,
              minimumSize: const Size.fromHeight(52),
              shape: buttonShape,
            ),
            onPressed: _approve,
            child: const Text(
              'Approve',
              style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
            ),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: OutlinedButton(
            style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(52),
              shape: buttonShape,
            ),
            onPressed: () => _say('Editing arrives in the next update.'),
            child: const Text('Edit'),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: OutlinedButton(
            style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(52),
              shape: buttonShape,
            ),
            onPressed: _reject,
            child: const Text('Reject'),
          ),
        ),
      ],
    );
  }

  Widget _cardShell({required Widget child, Color? bg, Color? border}) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: bg ?? Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: border ?? const Color(0xFFE3E1D8)),
        ),
        child: child,
      ),
    );
  }

  Widget _proposedCard(Proposal proposal) {
    return _cardShell(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _header(proposal),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _pill(
                '${(proposal.confidence * 100).round()}% sure',
                bg: AccnomosColors.tealTint,
                fg: AccnomosColors.tealDark,
              ),
              _pill(
                proposal.source,
                bg: AccnomosColors.ground,
                fg: AccnomosColors.ink,
              ),
            ],
          ),
          const Divider(height: 24),
          _fieldRow('Category', proposal.category),
          if (proposal.net != null)
            _fieldRow('Net', _gbp(proposal.net!)),
          if (proposal.vat != null)
            _fieldRow('VAT to reclaim (20%)', _gbp(proposal.vat!)),
          if (proposal.vatNumber != null)
            _fieldRow('VAT number ✓', proposal.vatNumber!),
          if (proposal.reviewerNote != null)
            _noteBox(
              'Why: ${proposal.reviewerNote}',
              bg: AccnomosColors.ground,
              fg: AccnomosColors.ink,
            ),
          _noteBox(
            proposal.verifierNote ??
                'Verifier agrees · all 5 fields match.',
            bg: AccnomosColors.tealTint,
            fg: AccnomosColors.tealDark,
          ),
          const SizedBox(height: 4),
          _alwaysRow(proposal),
          const SizedBox(height: 8),
          _decisionRow(),
        ],
      ),
    );
  }

  Widget _needsALookCard(Proposal proposal) {
    final buttonShape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(14),
    );
    return _cardShell(
      bg: _warnBg,
      border: _warnBorder,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _header(proposal, ink: _warnInk),
          const SizedBox(height: 10),
          _pill('Needs a look', bg: _warnBorder, fg: _warnInk),
          const SizedBox(height: 10),
          Text(
            proposal.reason ?? '',
            style: const TextStyle(color: _warnInk, height: 1.4),
          ),
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: _warnInk,
                minimumSize: const Size.fromHeight(52),
                shape: buttonShape,
              ),
              onPressed: () {
                _say('Archived as duplicate');
                _advance();
              },
              child: const Text(
                'Archive as duplicate',
                style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
              ),
            ),
          ),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
              style: OutlinedButton.styleFrom(
                foregroundColor: _warnInk,
                side: const BorderSide(color: _warnInk),
                minimumSize: const Size.fromHeight(52),
                shape: buttonShape,
              ),
              onPressed: () =>
                  _say('Comparison arrives in the next update.'),
              child: const Text("It's different — compare"),
            ),
          ),
        ],
      ),
    );
  }

  Widget _voiceCard(Proposal proposal) {
    return _cardShell(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _header(proposal),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _pill(
                '${(proposal.confidence * 100).round()}% sure',
                bg: AccnomosColors.tealTint,
                fg: AccnomosColors.tealDark,
              ),
              _pill(
                'Voice note',
                bg: AccnomosColors.ground,
                fg: AccnomosColors.ink,
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            '“${proposal.quote ?? ''}”',
            style: const TextStyle(
              fontStyle: FontStyle.italic,
              fontSize: 16,
              height: 1.4,
              color: AccnomosColors.ink,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'No VAT receipt, so no VAT claimed.',
            style: TextStyle(color: AccnomosColors.muted),
          ),
          const SizedBox(height: 4),
          _alwaysRow(proposal),
          const SizedBox(height: 8),
          _decisionRow(),
        ],
      ),
    );
  }
}
