import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../theme.dart';

/// Base of the production web app. Deep links below append a page path
/// (e.g. `/bank`), matching the Next.js routes in `apps/web/src/app`.
const webAppBase = 'https://accnomos.com';

/// "Do this on the web": a clear row for anything left web-only, with a
/// link to the exact page. Shown at the end of the phone screen that
/// covers the neighbouring actions.
class WebOnlyCard extends StatelessWidget {
  const WebOnlyCard({
    super.key,
    required this.message,
    required this.page,
    this.linkLabel = 'Do this on the web',
  });

  /// Plain-English sentence naming what stays on the web, e.g.
  /// "Uploading a statement CSV happens on the web."
  final String message;

  /// Web page path, e.g. `/bank`.
  final String page;

  final String linkLabel;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.open_in_browser_outlined,
                  size: 18, color: AccnomosColors.muted),
              SizedBox(width: 6),
              Text('On the web',
                  style: TextStyle(
                      fontWeight: FontWeight.w800,
                      color: AccnomosColors.muted,
                      fontSize: 12,
                      letterSpacing: 0.6)),
            ],
          ),
          const SizedBox(height: 6),
          Text(message,
              style: const TextStyle(
                  color: AccnomosColors.ink, height: 1.4, fontSize: 14)),
          const SizedBox(height: 8),
          TextButton.icon(
            style: TextButton.styleFrom(
              padding: EdgeInsets.zero,
              minimumSize: const Size(48, 48),
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
            icon: const Icon(Icons.open_in_new_outlined, size: 16),
            label: Text(linkLabel,
                style: const TextStyle(fontWeight: FontWeight.w800)),
            onPressed: () async {
              final launched = await launchUrl(
                Uri.parse('$webAppBase$page'),
                mode: LaunchMode.externalApplication,
              );
              if (!launched && context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('Could not open $page.')),
                );
              }
            },
          ),
        ],
      ),
    );
  }
}
