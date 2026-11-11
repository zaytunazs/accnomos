import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../theme.dart';
import '../widgets/web_only.dart' show webAppBase;
import 'navigation.dart';
import 'store_policy.dart';

/// The web's Settings › Plan & billing page. The app never sells anything
/// itself (no Google Play billing): plans, cards and top-ups are managed there.
const planBillingUrl = '$webAppBase/settings#plan-billing';

/// A refused request: HTTP 402 from the runtime
/// (services/runtime/app/billing/service.py), top level or under `detail`:
///
/// * `{"code": "plan_limit", "counter", "limit", "used", "upgrade_url", "detail"}`:
///   an allowance is used up;
/// * `{"code": "read_only", "status", "upgrade_url", "detail"}`: the trial
///   ended or the plan was cancelled, so the books can be viewed and exported
///   but nothing added.
///
/// The same bodies the web's `lib/plan-limit.ts` reads.
class PlanLimitInfo {
  const PlanLimitInfo(
      {this.code = 'plan_limit',
      this.counter,
      this.limit,
      this.used,
      this.status,
      this.detail});

  /// `plan_limit` or `read_only`.
  final String code;

  /// docs, ask, invoices, bank_feeds, users, marketplaces, payroll_employees,
  /// autopilot_rules (plan_limit only).
  final String? counter;
  final int? limit;
  final int? used;

  /// trial_ended or cancelled (read_only only).
  final String? status;

  /// The runtime's own sentence.
  final String? detail;

  bool get readOnly => code == 'read_only';

  /// Null unless [status] is 402 and the body is `plan_limit` or `read_only`.
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
    String? text(Object? v) => v is String && v.isNotEmpty ? v : null;
    int? whole(Object? v) => v is int ? v : null;
    switch (inner['code']) {
      case 'plan_limit':
        return PlanLimitInfo(
          counter: text(inner['counter']),
          limit: whole(inner['limit']),
          used: whole(inner['used']),
          detail: text(inner['detail']),
        );
      case 'read_only':
        return PlanLimitInfo(
          code: 'read_only',
          status: text(inner['status']),
          detail: text(inner['detail']),
        );
    }
    return null;
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
  static const _monthly = {'docs', 'ask', 'invoices'};
  static const _nothingLost =
      'Nothing is lost: you can still approve, edit and export everything already in your books.';

  bool get _cancelled => status == 'cancelled';

  /// The dialog's title.
  String get title => readOnly
      ? (_cancelled ? 'Your plan has been cancelled' : 'Your free trial has ended')
      : "You have reached your plan's limit";

  /// Friendly, never blaming, and says nothing is locked away. Never mentions
  /// buying or a website: [PlanLimitDialog] adds that only where
  /// [StorePolicy.purchaseLinksAllowed].
  String get sentence {
    if (readOnly) {
      final why = _cancelled ? 'Your plan has been cancelled' : 'Your free trial has ended';
      return '$why, so your books are read-only. Everything is still there: you can view and export it.';
    }
    final what = _words[counter];
    if (what == null) return 'You have reached a limit on your plan. $_nothingLost';
    if (limit == 0) return 'Your plan does not include $what. $_nothingLost';
    final all = limit == null ? 'all of' : 'all $limit of';
    final lead = _monthly.contains(counter)
        ? "You have used $all this month's $what on your plan."
        : 'Your plan allows ${limit ?? 'a set number of'} $what, and that many are already set up.';
    return '$lead $_nothingLost';
  }
}

/// The one dialog for every 402 (plan limit or read-only), shown over whatever
/// screen is open.
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
  const PlanLimitDialog(
      {super.key, required this.info, this.open, this.purchaseLinksAllowed});

  final PlanLimitInfo info;

  /// Test seam for opening the web page.
  final Future<void> Function(Uri uri)? open;

  /// Test seam for [StorePolicy.purchaseLinksAllowed]. On iOS the dialog
  /// says what happened and what still works, with no link, price or
  /// "on the web" (App Store Review Guidelines 3.1.1 and 3.1.3).
  final bool? purchaseLinksAllowed;

  @override
  Widget build(BuildContext context) {
    final links = purchaseLinksAllowed ?? StorePolicy.purchaseLinksAllowed;
    final String? where = !links
        ? null
        : info.readOnly
            ? 'Choose a plan on the web to carry on adding and changing things.'
            : 'You can buy 100 more documents or change plan on the web. Usage resets on the 1st of each month.';
    return AlertDialog(
      key: const Key('plan-limit-dialog'),
      title: Text(info.title),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(info.sentence),
          if (!info.readOnly && !links) ...[
            const SizedBox(height: 8),
            const Text('Usage resets on the 1st of each month.',
                style: TextStyle(color: AccnomosColors.muted)),
          ],
          if (where != null) ...[
            const SizedBox(height: 8),
            Text(where, style: const TextStyle(color: AccnomosColors.muted)),
          ],
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(links ? 'Not now' : 'OK'),
        ),
        if (links)
          FilledButton(
            key: const Key('plan-limit-open-web'),
            onPressed: () async {
              final uri = Uri.parse(planBillingUrl);
              await (open ??
                  (u) => launchUrl(u, mode: LaunchMode.externalApplication))(uri);
              if (context.mounted) Navigator.of(context).pop();
            },
            child: Text(info.readOnly ? 'Choose a plan on the web' : 'Manage plan on the web'),
          ),
      ],
    );
  }
}
