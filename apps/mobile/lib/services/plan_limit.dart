import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../theme.dart';
import '../widgets/web_only.dart' show webAppBase;
import 'navigation.dart';

/// The web's Settings › Plan & billing page. The app never sells anything
/// itself (no Google Play billing): plans, cards and top-ups are managed there.
const planBillingUrl = '$webAppBase/settings#plan-billing';

/// A refused request at a plan limit: HTTP 402 `{"code": "plan_limit"}`
/// (docs/billing/PLANS_AND_CONTRACT.md), the same body the web's
/// `lib/plan-limit.ts` reads, top level or under `detail`.
class PlanLimitInfo {
  const PlanLimitInfo({this.message, this.limitKey});

  final String? message;

  /// docs, ask, invoices, bank_feeds, users, marketplaces, payroll_employees, ...
  final String? limitKey;

  /// Null unless [status] is 402 and the body says `plan_limit`.
  static PlanLimitInfo? parse(int status, String body) {
    if (status != 402) return null;
    Object? decoded;
    try {
      decoded = json.decode(body);
    } catch (_) {
      return null;
    }
    if (decoded is! Map) return null;
    final detail = decoded['detail'];
    final inner = detail is Map ? detail : decoded;
    if (inner['code'] != 'plan_limit') return null;
    String? text(Object? v) => v is String && v.isNotEmpty ? v : null;
    return PlanLimitInfo(
      message: text(inner['message']),
      limitKey: text(inner['limit']) ?? text(inner['limit_key']) ?? text(inner['feature']),
    );
  }

  static const _words = {
    'docs': 'AI-read documents',
    'ask': 'Ask questions',
    'invoices': 'sales invoices and quotes',
    'bank_feeds': 'live bank feeds',
    'users': 'users',
    'marketplaces': 'marketplace connections',
    'payroll_employees': 'payroll employees',
    'autopilot_rules': 'Autopilot rules',
  };

  /// Friendly, never blaming, and says nothing is locked away.
  String get sentence {
    final what = _words[limitKey];
    final lead = what != null
        ? "You have reached this month's limit for $what on your plan."
        : 'You have reached a limit on your plan.';
    return '$lead Nothing is lost: you can still approve, edit and export everything already in your books.';
  }
}

/// The one dialog for every 402 plan limit, shown over whatever screen is open.
class PlanLimit {
  PlanLimit._();

  static bool _showing = false;

  /// Test hook: the last limit shown.
  static PlanLimitInfo? last;

  static Future<void> show(PlanLimitInfo info, {BuildContext? context}) async {
    last = info;
    final ctx = context ?? appNavigatorKey.currentContext;
    if (ctx == null || _showing) return;
    _showing = true;
    try {
      await showDialog<void>(
        context: ctx,
        builder: (_) => PlanLimitDialog(info: info),
      );
    } finally {
      _showing = false;
    }
  }
}

class PlanLimitDialog extends StatelessWidget {
  const PlanLimitDialog({super.key, required this.info, this.open});

  final PlanLimitInfo info;

  /// Test seam for opening the web page.
  final Future<void> Function(Uri uri)? open;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      key: const Key('plan-limit-dialog'),
      title: const Text("You have reached your plan's limit"),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(info.sentence),
          if (info.message != null) ...[
            const SizedBox(height: 8),
            Text(info.message!, style: const TextStyle(color: AccnomosColors.muted)),
          ],
          const SizedBox(height: 8),
          const Text(
              'You can buy 100 more documents or change plan on the web. Usage resets on the 1st of each month.',
              style: TextStyle(color: AccnomosColors.muted)),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Not now'),
        ),
        FilledButton(
          key: const Key('plan-limit-open-web'),
          onPressed: () async {
            final uri = Uri.parse(planBillingUrl);
            await (open ?? (u) => launchUrl(u, mode: LaunchMode.externalApplication))(uri);
            if (context.mounted) Navigator.of(context).pop();
          },
          child: const Text('Manage plan on the web'),
        ),
      ],
    );
  }
}
