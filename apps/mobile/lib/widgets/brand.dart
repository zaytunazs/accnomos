import 'package:flutter/material.dart';

import '../services/navigation.dart';
import '../theme.dart';

/// The Accnomos mark, as the web draws it (apps/web/src/components/TopBar.tsx
/// `LogoMark`): a teal rounded square with a light hexagon and a tick.
class LogoMark extends StatelessWidget {
  const LogoMark({super.key, this.size = 36, this.onDark = false});

  final double size;

  /// On the dark-brown hero band: a thin gold ring so the brown tile still reads.
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
  // The Zaytuna mark (apps/web/public/brand/zaytuna/icon.svg, 108×108 viewBox): an olive branch whose stem is a
  // tick, with a gold smile under it. The tile behind it is the Container's brown.
  static const _cream = Color(0xFFF4EDE5);
  static const _gold = Color(0xFFC9A45C);
  static const _olive = Color(0xFF8A9A3B);

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.width / 108;
    canvas.save();
    canvas.scale(s, s);
    final stroke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    // Tick stem: M33 50 c8 6 14 12 18 20 c7 -21 17 -35 25 -45
    final tick = Path()
      ..moveTo(33, 50)
      ..cubicTo(41, 56, 47, 62, 51, 70)
      ..cubicTo(58, 49, 68, 35, 76, 25);
    canvas.drawPath(tick, stroke..color = _cream..strokeWidth = size.width < 30 ? 9 : 7);
    if (size.width >= 30) {
      void leaf(double cx, double cy, double rx, double ry, double deg, Color c) {
        canvas.save();
        canvas.translate(cx, cy);
        canvas.rotate(deg * 3.141592653589793 / 180);
        canvas.drawOval(Rect.fromCenter(center: Offset.zero, width: rx * 2, height: ry * 2), Paint()..color = c);
        canvas.restore();
      }

      leaf(45, 38, 5.5, 12, -40, _gold);
      leaf(64, 32, 5, 11, 35, _gold);
      leaf(72, 49, 4.5, 10, 70, _olive);
    }
    // Smile: M32 78 q22 16 44 0
    final smile = Path()
      ..moveTo(32, 78)
      ..quadraticBezierTo(54, 94, 76, 78);
    canvas.drawPath(smile, stroke..color = _gold..strokeWidth = size.width < 30 ? 9 : 6.5);
    canvas.restore();
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
    return IconButton(
      key: const Key('logo-home'),
      tooltip: 'Home',
      onPressed: AppNav.goHome,
      icon: const LogoMark(size: 28),
    );
  }
}

/// The logo and wordmark as a button: tap to go Home, as the website's logo
/// does. Used as the Home app bar's title.
class HomeLogoButton extends StatelessWidget {
  const HomeLogoButton({super.key, this.size = 30});

  final double size;

  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        label: 'Accnomos, go to Home',
        child: InkWell(
          key: const Key('logo-lockup-home'),
          borderRadius: BorderRadius.circular(8),
          onTap: AppNav.goHome,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 2),
            child: ExcludeSemantics(child: BrandLockup(size: size)),
          ),
        ),
      );
}
