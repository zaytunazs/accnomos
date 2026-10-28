import 'package:flutter/material.dart';

/// Shared Accnomos palette. Previously private constants in `main.dart`.
class AccnomosColors {
  const AccnomosColors._();

  static const Color ink = Color(0xFF1B1F24);
  static const Color teal = Color(0xFF0F6E63);
  static const Color tealDark = Color(0xFF0A4F47);
  static const Color tealTint = Color(0xFFE6F1EF);
  static const Color ground = Color(0xFFF4F3EE);
  static const Color muted = Color(0xFF4B5159);

  /// Budget progress states on the Personal screen: on track, close to
  /// the limit, and over it.
  static const Color budgetOk = Color(0xFF0A4F47);
  static const Color budgetNear = Color(0xFFB7791F);
  static const Color budgetOver = Color(0xFFB3261E);
}
