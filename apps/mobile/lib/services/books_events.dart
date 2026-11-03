import 'package:flutter/foundation.dart';

/// A tick that goes up whenever the app changes the books (an approve, a
/// reject, an undo, a bank match, a saved invoice…), so screens that show
/// totals — Home, VAT — reload instead of showing what they read before.
/// [RuntimeClient] bumps it after every successful request that is not a GET.
class BooksEvents {
  BooksEvents._();

  static final ValueNotifier<int> changed = ValueNotifier(0);

  static void bump() => changed.value++;
}
