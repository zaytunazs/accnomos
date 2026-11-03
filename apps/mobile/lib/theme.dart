import 'package:flutter/material.dart';

/// Shared Accnomos palette: the same tokens as the website
/// (apps/web/src/app/globals.css, the teal-and-white restyle).
class AccnomosColors {
  const AccnomosColors._();

  /// Headings, body text and financial figures.
  static const Color ink = Color(0xFF172B35);
  static const Color teal = Color(0xFF0F6E63);
  static const Color tealDark = Color(0xFF0A4F47);
  static const Color tealTint = Color(0xFFE8F4F1);

  /// The page behind the cards.
  static const Color ground = Color(0xFFF5F8FA);
  static const Color muted = Color(0xFF52626D);

  /// Card outlines and separators.
  static const Color border = Color(0xFFDCE5E9);

  /// The dark-teal navigation and hero colours (the web's sidebar / ledger).
  static const Color sidebar = Color(0xFF0B3F43);
  static const Color sidebarActive = Color(0xFF17666A);
  static const Color ledger = Color(0xFF0A4F47);

  /// The brand gold: a small accent only, never text on white.
  static const Color brass = Color(0xFFD9B55A);

  /// Light strokes and text on the dark-teal bands.
  static const Color markLight = Color(0xFFF4F3EE);

  /// Status text and tints (favourable, attention, negative, information).
  static const Color posText = Color(0xFF166534);
  static const Color posTint = Color(0xFFECFDF3);
  static const Color warnText = Color(0xFF8A470D);
  static const Color warnTint = Color(0xFFFFF4DC);
  static const Color negText = Color(0xFFA12626);
  static const Color negTint = Color(0xFFFFF0F0);
  static const Color infoText = Color(0xFF175C86);
  static const Color infoTint = Color(0xFFEDF6FF);

  /// Budget progress states on the Personal screen: on track, close to
  /// the limit, and over it.
  static const Color budgetOk = Color(0xFF0A4F47);
  static const Color budgetNear = Color(0xFFB7791F);
  static const Color budgetOver = Color(0xFFB3261E);
}

/// The app's one theme: set here, not screen by screen. Cards are white with
/// a 1 px border and 12 px corners, buttons and fields 8 px and at least
/// 44 px tall, one filled teal primary action; the bottom bar marks the
/// current tab in teal on a teal tint. Every text colour on white or the
/// page background is at least 4.5:1.
ThemeData accnomosTheme() {
  const radius8 = BorderRadius.all(Radius.circular(8));
  final scheme = ColorScheme.fromSeed(
    seedColor: AccnomosColors.teal,
    primary: AccnomosColors.teal,
    onPrimary: Colors.white,
    secondary: AccnomosColors.tealDark,
    surface: Colors.white,
    onSurface: AccnomosColors.ink,
    onSurfaceVariant: AccnomosColors.muted,
    outline: AccnomosColors.border,
    outlineVariant: AccnomosColors.border,
    error: AccnomosColors.negText,
  );
  const minSize = Size(64, 44);
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: AccnomosColors.ground,
    dividerColor: AccnomosColors.border,
    textTheme: const TextTheme(
      headlineMedium: TextStyle(
          fontWeight: FontWeight.w700, color: AccnomosColors.ink, height: 1.2),
      headlineSmall: TextStyle(
          fontWeight: FontWeight.w700, color: AccnomosColors.ink, height: 1.2),
      titleLarge: TextStyle(
          fontWeight: FontWeight.w700, color: AccnomosColors.ink, height: 1.2),
      titleMedium:
          TextStyle(fontWeight: FontWeight.w600, color: AccnomosColors.ink),
      bodyLarge: TextStyle(color: AccnomosColors.ink, height: 1.5),
      bodyMedium: TextStyle(color: AccnomosColors.ink, height: 1.5),
      bodySmall: TextStyle(color: AccnomosColors.muted),
      labelLarge: TextStyle(fontWeight: FontWeight.w600),
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: Colors.white,
      foregroundColor: AccnomosColors.ink,
      surfaceTintColor: Colors.white,
      elevation: 0,
      scrolledUnderElevation: 0.5,
      shape: Border(bottom: BorderSide(color: AccnomosColors.border)),
      titleTextStyle: TextStyle(
          fontSize: 20, fontWeight: FontWeight.w700, color: AccnomosColors.ink),
    ),
    cardTheme: const CardThemeData(
      color: Colors.white,
      surfaceTintColor: Colors.white,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(12)),
        side: BorderSide(color: AccnomosColors.border),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: AccnomosColors.teal,
        foregroundColor: Colors.white,
        minimumSize: minSize,
        shape: const RoundedRectangleBorder(borderRadius: radius8),
        textStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: AccnomosColors.teal,
        foregroundColor: Colors.white,
        elevation: 0,
        minimumSize: minSize,
        shape: const RoundedRectangleBorder(borderRadius: radius8),
        textStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: AccnomosColors.tealDark,
        backgroundColor: Colors.white,
        minimumSize: minSize,
        side: const BorderSide(color: AccnomosColors.border),
        shape: const RoundedRectangleBorder(borderRadius: radius8),
        textStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: AccnomosColors.tealDark,
        minimumSize: const Size(44, 44),
        textStyle: const TextStyle(fontWeight: FontWeight.w700),
      ),
    ),
    inputDecorationTheme: const InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      border: OutlineInputBorder(
          borderRadius: radius8,
          borderSide: BorderSide(color: AccnomosColors.border)),
      enabledBorder: OutlineInputBorder(
          borderRadius: radius8,
          borderSide: BorderSide(color: AccnomosColors.border)),
      focusedBorder: OutlineInputBorder(
          borderRadius: radius8,
          borderSide: BorderSide(color: AccnomosColors.tealDark, width: 2)),
      labelStyle: TextStyle(color: AccnomosColors.muted),
    ),
    chipTheme: const ChipThemeData(
      backgroundColor: Colors.white,
      side: BorderSide(color: AccnomosColors.border),
      shape: RoundedRectangleBorder(borderRadius: radius8),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: Colors.white,
      surfaceTintColor: Colors.white,
      indicatorColor: AccnomosColors.tealTint,
      elevation: 0,
      height: 68,
      iconTheme: WidgetStateProperty.resolveWith((states) => IconThemeData(
            color: states.contains(WidgetState.selected)
                ? AccnomosColors.teal
                : AccnomosColors.muted,
          )),
      labelTextStyle: WidgetStateProperty.resolveWith((states) => TextStyle(
            fontSize: 12,
            fontWeight: states.contains(WidgetState.selected)
                ? FontWeight.w700
                : FontWeight.w500,
            color: states.contains(WidgetState.selected)
                ? AccnomosColors.tealDark
                : AccnomosColors.muted,
          )),
    ),
    dividerTheme:
        const DividerThemeData(color: AccnomosColors.border, thickness: 1),
    snackBarTheme: const SnackBarThemeData(
      backgroundColor: AccnomosColors.ink,
      behavior: SnackBarBehavior.floating,
    ),
  );
}
