import 'package:flutter/material.dart';

/// Home tiles two to a row. Unlike a fixed-ratio GridView, each row is as
/// tall as its tallest tile, so labels wrap at large text sizes instead of
/// being cut off ("Lines with no cate…"), and no safe-area padding is added
/// above the first row.
class TileGrid extends StatelessWidget {
  const TileGrid({
    super.key,
    required this.children,
    this.spacing = 12,
    this.minTileHeight = 112,
  });

  final List<Widget> children;
  final double spacing;
  final double minTileHeight;

  @override
  Widget build(BuildContext context) {
    final rows = <Widget>[];
    for (var i = 0; i < children.length; i += 2) {
      if (rows.isNotEmpty) rows.add(SizedBox(height: spacing));
      Widget cell(Widget w) => Expanded(
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: minTileHeight),
              child: w,
            ),
          );
      rows.add(IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            cell(children[i]),
            SizedBox(width: spacing),
            if (i + 1 < children.length)
              cell(children[i + 1])
            else
              const Expanded(child: SizedBox()),
          ],
        ),
      ));
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: rows,
    );
  }
}
