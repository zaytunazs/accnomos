import 'package:flutter/material.dart';

import '../theme.dart';

/// A soft light sweeping across grey placeholder shapes while a section
/// loads. Still (plain grey) when the phone asks for reduced motion.
class Shimmer extends StatefulWidget {
  const Shimmer({super.key, required this.child});

  final Widget child;

  @override
  State<Shimmer> createState() => _ShimmerState();
}

class _ShimmerState extends State<Shimmer> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
      vsync: this, duration: const Duration(milliseconds: 1400));

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final still = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    if (still) {
      _c.stop();
    } else if (!_c.isAnimating) {
      _c.repeat();
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final still = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    if (still) return widget.child;
    return AnimatedBuilder(
      animation: _c,
      child: widget.child,
      builder: (context, child) {
        final t = _c.value * 2 - 0.5; // -0.5 → 1.5: the light enters and leaves
        return ShaderMask(
          blendMode: BlendMode.srcATop,
          shaderCallback: (rect) => LinearGradient(
            colors: const [
              Color(0xFFE6ECEF),
              Color(0xFFF7FAFB),
              Color(0xFFE6ECEF),
            ],
            stops: [t - 0.3, t, t + 0.3].map((s) => s.clamp(0.0, 1.0)).toList(),
          ).createShader(rect),
          child: child,
        );
      },
    );
  }
}

/// One grey bar or block of a placeholder.
class SkeletonBox extends StatelessWidget {
  const SkeletonBox({super.key, this.width, this.height = 12, this.radius = 6});

  final double? width;
  final double height;
  final double radius;

  @override
  Widget build(BuildContext context) => Container(
        width: width,
        height: height,
        decoration: BoxDecoration(
          color: const Color(0xFFE6ECEF),
          borderRadius: BorderRadius.circular(radius),
        ),
      );
}

/// A white card shaped like the one that is coming: an optional real title,
/// then shimmering bars. Never an empty gap or a spinner on its own.
class SkeletonCard extends StatelessWidget {
  const SkeletonCard({
    super.key,
    this.title,
    this.lines = 3,
    this.height,
    this.tinted = false,
  });

  final String? title;
  final int lines;
  final double? height;
  final bool tinted;

  @override
  Widget build(BuildContext context) {
    const widths = [1.0, 0.82, 0.64, 0.9, 0.5];
    return Semantics(
      label: '${title ?? 'Section'}, loading',
      child: Container(
        height: height,
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: tinted ? AccnomosColors.tealTint : Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
              color: tinted ? const Color(0xFFC9E2DC) : AccnomosColors.border),
        ),
        child: ExcludeSemantics(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (title != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Text(title!,
                      style: const TextStyle(
                          fontWeight: FontWeight.w700, fontSize: 16)),
                ),
              Shimmer(
                child: LayoutBuilder(
                  builder: (context, c) => Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      for (var i = 0; i < lines; i++)
                        Padding(
                          padding: EdgeInsets.only(top: i == 0 ? 0 : 10),
                          child: SkeletonBox(
                              width: c.maxWidth * widths[i % widths.length]),
                        ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// A Home tile still loading: same size as a real tile.
class SkeletonTile extends StatelessWidget {
  const SkeletonTile({super.key, required this.label});

  final String label;

  @override
  Widget build(BuildContext context) => Semantics(
        label: '$label, loading',
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AccnomosColors.border),
          ),
          child: ExcludeSemantics(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label,
                    style: const TextStyle(
                        color: AccnomosColors.muted, fontSize: 13)),
                const SizedBox(height: 10),
                const Shimmer(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SkeletonBox(width: 90, height: 22),
                      SizedBox(height: 8),
                      SkeletonBox(width: 120, height: 10),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      );
}

/// The thin teal bar and line shown while the AI rewords a summary or note
/// that code has already written.
class AiWritingBar extends StatelessWidget {
  const AiWritingBar({super.key, required this.label});

  final String label;

  @override
  Widget build(BuildContext context) => Semantics(
        liveRegion: true,
        label: label,
        child: ExcludeSemantics(
          child: Row(
            children: [
              const SizedBox(
                width: 14,
                height: 14,
                child: CircularProgressIndicator(
                    strokeWidth: 2, color: AccnomosColors.teal),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(label,
                    style: const TextStyle(
                        color: AccnomosColors.tealDark,
                        fontSize: 12,
                        fontWeight: FontWeight.w600)),
              ),
            ],
          ),
        ),
      );
}
