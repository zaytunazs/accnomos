import 'package:flutter/material.dart';

import '../theme.dart';

/// The Accnomos mark, as the web draws it (apps/web/src/components/TopBar.tsx
/// `LogoMark`): a teal rounded square with a light hexagon and a tick.
class LogoMark extends StatelessWidget {
  const LogoMark({super.key, this.size = 36, this.onDark = false});

  final double size;

  /// On the dark-teal hero band: a lighter square so the mark still reads.
  final bool onDark;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Accnomos',
      image: true,
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          color: AccnomosColors.teal,
          borderRadius: BorderRadius.circular(size * 0.22),
          border: onDark
              ? Border.all(color: AccnomosColors.brass.withValues(alpha: 0.7))
              : null,
        ),
        child: CustomPaint(painter: _MarkPainter()),
      ),
    );
  }
}

class _MarkPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    // The web's 20×20 viewBox, centred at 20/36 of the square.
    final s = size.width * 20 / 36 / 20;
    final dx = (size.width - 20 * s) / 2;
    final dy = (size.height - 20 * s) / 2;
    Offset p(double x, double y) => Offset(dx + x * s, dy + y * s);
    final paint = Paint()
      ..color = AccnomosColors.markLight
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.8 * s
      ..strokeJoin = StrokeJoin.round
      ..strokeCap = StrokeCap.round;
    final hex = Path()
      ..moveTo(p(10, 2.5).dx, p(10, 2.5).dy)
      ..lineTo(p(16.5, 6).dx, p(16.5, 6).dy)
      ..lineTo(p(16.5, 14).dx, p(16.5, 14).dy)
      ..lineTo(p(10, 17.5).dx, p(10, 17.5).dy)
      ..lineTo(p(3.5, 14).dx, p(3.5, 14).dy)
      ..lineTo(p(3.5, 6).dx, p(3.5, 6).dy)
      ..close();
    canvas.drawPath(hex, paint);
    final tick = Path()
      ..moveTo(p(7, 10.2).dx, p(7, 10.2).dy)
      ..lineTo(p(9.1, 12.3).dx, p(9.1, 12.3).dy)
      ..lineTo(p(13.2, 8).dx, p(13.2, 8).dy);
    canvas.drawPath(tick, paint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

/// Logo mark and the "Accnomos" wordmark, for app bars and the Welcome hero.
class BrandLockup extends StatelessWidget {
  const BrandLockup({super.key, this.onDark = false, this.size = 32});

  final bool onDark;
  final double size;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        LogoMark(size: size, onDark: onDark),
        SizedBox(width: size * 0.32),
        Text(
          'Accnomos',
          style: TextStyle(
            fontSize: size * 0.62,
            fontWeight: FontWeight.w800,
            letterSpacing: -0.3,
            color: onDark ? AccnomosColors.markLight : AccnomosColors.ink,
          ),
        ),
      ],
    );
  }
}


/// The leading slot of a tab screen's app bar: the logo mark, or the back button when the screen was pushed (Goals and
/// Budget open from More for a business), so every screen carries the brand without losing its way back.
class BrandLeading extends StatelessWidget {
  const BrandLeading({super.key});

  @override
  Widget build(BuildContext context) {
    if (Navigator.of(context).canPop()) return const BackButton();
    return const Padding(
      padding: EdgeInsets.all(12),
      child: LogoMark(size: 28),
    );
  }
}
