import 'package:flutter/material.dart';

/// Accnomos — bookkeeping and VAT for UK small businesses.
/// Your books stay in your own cloud. Meta AI does the work.
///
/// v0.1.0: app shell (Home · Review · Ask · Files). Features arrive day by day;
/// see CHANGELOG.md in the repo.
void main() => runApp(const AccnomosApp());

const _ink = Color(0xFF1B1F24);
const _teal = Color(0xFF0F6E63);
const _tealDark = Color(0xFF0A4F47);
const _tealTint = Color(0xFFE6F1EF);
const _ground = Color(0xFFF4F3EE);
const _muted = Color(0xFF4B5159);

class AccnomosApp extends StatelessWidget {
  const AccnomosApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Accnomos',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        scaffoldBackgroundColor: _ground,
        colorScheme: ColorScheme.fromSeed(
          seedColor: _teal,
          primary: _teal,
          surface: Colors.white,
        ),
        textTheme: const TextTheme(
          headlineSmall: TextStyle(fontWeight: FontWeight.w800, color: _ink),
          titleMedium: TextStyle(fontWeight: FontWeight.w700, color: _ink),
          bodyMedium: TextStyle(color: _ink),
        ),
      ),
      home: const Shell(),
    );
  }
}

class Shell extends StatefulWidget {
  const Shell({super.key});

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _tab = 0;

  static const _titles = ['Home', 'Review', 'Ask', 'Files'];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: _ground,
        elevation: 0,
        title: Text(_titles[_tab],
            style: Theme.of(context).textTheme.headlineSmall),
      ),
      body: Column(
        children: [
          const _SampleBanner(),
          Expanded(
            child: IndexedStack(
              index: _tab,
              children: const [
                _HomeTab(),
                _Placeholder(
                    'Review',
                    'Proposed entries from your receipts and invoices will appear here. '
                        'Nothing reaches your books until you tap Approve.'),
                _Placeholder(
                    'Ask',
                    'Ask your books a question, by text or voice. '
                        'Every answer cites the files it came from.'),
                _Placeholder('Files',
                    'A live view of the Accnomos folder in your own cloud storage.'),
              ],
            ),
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        indicatorColor: _tealTint,
        destinations: const [
          NavigationDestination(icon: Icon(Icons.home_outlined), label: 'Home'),
          NavigationDestination(
              icon: Icon(Icons.checklist_outlined), label: 'Review'),
          NavigationDestination(
              icon: Icon(Icons.chat_bubble_outline), label: 'Ask'),
          NavigationDestination(
              icon: Icon(Icons.folder_outlined), label: 'Files'),
        ],
      ),
    );
  }
}

class _SampleBanner extends StatelessWidget {
  const _SampleBanner();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: _ink,
      padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 12),
      child: const Text(
        'SAMPLE — FICTIONAL COMPANY · demo data only',
        textAlign: TextAlign.center,
        style: TextStyle(
            color: _ground,
            fontSize: 11,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.6),
      ),
    );
  }
}

class _HomeTab extends StatelessWidget {
  const _HomeTab();

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('Your books. Your cloud. Meta AI on your terms.',
            style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 6),
        const Text(
          'Accnomos keeps your bookkeeping in a folder you own (OneDrive first), '
          'reads receipts and invoices with Meta AI, and files VAT returns to HMRC '
          'only when you say so.',
          style: TextStyle(color: _muted, height: 1.4),
        ),
        const SizedBox(height: 20),
        GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 12,
          crossAxisSpacing: 12,
          childAspectRatio: 1.35,
          children: const [
            _Tile(label: 'Cash in bank', value: '—', note: 'Connect to see'),
            _Tile(label: 'Owed to you', value: '—', note: 'Connect to see'),
            _Tile(label: 'VAT estimate', value: '—', note: 'Calculated by code'),
            _Tile(label: 'Needs attention', value: '0', note: 'Nothing waiting'),
          ],
        ),
        const SizedBox(height: 20),
        FilledButton(
          style: FilledButton.styleFrom(
              backgroundColor: _teal,
              minimumSize: const Size.fromHeight(52),
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14))),
          onPressed: () => ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
                content: Text('Microsoft sign-in arrives in the next update.')),
          ),
          child: const Text('Connect your cloud',
              style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
        ),
        const SizedBox(height: 10),
        const Text(
          'Accnomos never stores your data on its own servers.',
          textAlign: TextAlign.center,
          style: TextStyle(color: _muted, fontSize: 12),
        ),
      ],
    );
  }
}

class _Tile extends StatelessWidget {
  const _Tile({required this.label, required this.value, required this.note});
  final String label;
  final String value;
  final String note;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label.toUpperCase(),
              style: const TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: _muted,
                  letterSpacing: 0.6)),
          const Spacer(),
          Text(value,
              style: const TextStyle(
                  fontSize: 26, fontWeight: FontWeight.w800, color: _ink)),
          Text(note, style: const TextStyle(fontSize: 12, color: _muted)),
        ],
      ),
    );
  }
}

class _Placeholder extends StatelessWidget {
  const _Placeholder(this.title, this.body);
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(
                color: _tealTint, borderRadius: BorderRadius.circular(16)),
            child: const Icon(Icons.hourglass_top, color: _tealDark),
          ),
          const SizedBox(height: 14),
          Text(title, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 6),
          Text(body,
              textAlign: TextAlign.center,
              style: const TextStyle(color: _muted, height: 1.4)),
        ],
      ),
    );
  }
}
