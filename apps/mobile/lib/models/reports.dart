library;

/// Reports from `GET /reports/*` (see `services/runtime/app/reports.py`):
/// profit and loss, aged balances, VAT summary and monthly trend, worked
/// out by code from the user's own ledger events. Money is integer pence;
/// VAT boxes 6 and 7 are whole pounds. The phone never computes them.

int _pence(Object? v) => (v as num?)?.toInt() ?? 0;

/// "27 Oct 2026" from "2026-10-27", else the text itself.
String ukDate(String iso) {
  final text = iso.trim();
  if (text.isEmpty) return '—';
  try {
    final d = DateTime.parse(text);
    const months = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
    ];
    return '${d.day} ${months[d.month - 1]} ${d.year}';
  } catch (_) {
    return text;
  }
}

/// £1,234.56 from integer pence (negative as -£1.56).
String gbp(int pence) {
  final sign = pence < 0 ? '-' : '';
  final abs = pence.abs();
  final pounds = (abs ~/ 100).toString().replaceAllMapped(
      RegExp(r'\B(?=(\d{3})+(?!\d))'), (m) => ',');
  return '$sign£$pounds.${(abs % 100).toString().padLeft(2, '0')}';
}

/// One account row on the profit and loss.
class PlRow {
  PlRow({required this.account, required this.amountPence});

  final String account;
  final int amountPence;

  static PlRow fromJson(Map<String, dynamic> json) => PlRow(
        account: (json['account'] ?? '').toString(),
        amountPence: _pence(json['amount_pence']),
      );
}

class PlSection {
  PlSection({required this.rows, required this.totalPence});

  final List<PlRow> rows;
  final int totalPence;

  static PlSection fromJson(Map<String, dynamic> json) => PlSection(
        rows: [
          if (json['rows'] is List)
            for (final r in json['rows'] as List)
              if (r is Map) PlRow.fromJson(Map<String, dynamic>.from(r)),
        ],
        totalPence: _pence(json['total_pence']),
      );

  static PlSection empty() => PlSection(rows: const [], totalPence: 0);
}

/// `GET /reports/pl`.
class PlReport {
  PlReport({
    required this.start,
    required this.end,
    required this.label,
    required this.entries,
    required this.sales,
    required this.costOfSales,
    required this.grossPence,
    required this.overheads,
    required this.netPence,
    required this.sample,
  });

  final String start;
  final String end;
  final String label;
  final int entries;
  final PlSection sales;
  final PlSection costOfSales;
  final int grossPence;
  final PlSection overheads;
  final int netPence;
  final bool sample;

  static PlSection _section(Map<String, dynamic> json, String key) {
    final v = json[key];
    return v is Map ? PlSection.fromJson(Map<String, dynamic>.from(v)) : PlSection.empty();
  }

  factory PlReport.fromJson(Map<String, dynamic> json) => PlReport(
        start: (json['start'] ?? '').toString(),
        end: (json['end'] ?? '').toString(),
        label: (json['label'] ?? '').toString(),
        entries: _pence(json['entries']),
        sales: _section(json, 'sales'),
        costOfSales: _section(json, 'cost_of_sales'),
        grossPence: _pence(json['gross_profit_pence']),
        overheads: _section(json, 'overheads'),
        netPence: _pence(json['net_profit_pence']),
        sample: json['sample'] == true,
      );
}

/// One unpaid contact on an aged table.
class AgedRow {
  AgedRow({required this.name, required this.buckets, required this.totalPence});

  final String name;
  final Map<String, int> buckets;
  final int totalPence;

  static AgedRow fromJson(Map<String, dynamic> json) {
    final buckets = <String, int>{};
    final raw = json['buckets'];
    if (raw is Map) {
      for (final e in raw.entries) {
        buckets[e.key.toString()] = _pence(e.value);
      }
    }
    return AgedRow(
      name: (json['name'] ?? '').toString(),
      buckets: buckets,
      totalPence: _pence(json['total_pence']),
    );
  }
}

/// Debtors or creditors: rows plus the column totals.
class AgedTable {
  AgedTable({required this.rows, required this.buckets, required this.totalPence});

  final List<AgedRow> rows;
  final Map<String, int> buckets;
  final int totalPence;

  static AgedTable fromJson(Map<String, dynamic> json) {
    final buckets = <String, int>{};
    final raw = json['buckets'];
    if (raw is Map) {
      for (final e in raw.entries) {
        buckets[e.key.toString()] = _pence(e.value);
      }
    }
    return AgedTable(
      rows: [
        if (json['rows'] is List)
          for (final r in json['rows'] as List)
            if (r is Map) AgedRow.fromJson(Map<String, dynamic>.from(r)),
      ],
      buckets: buckets,
      totalPence: _pence(json['total_pence']),
    );
  }
}

/// `GET /reports/aged`.
class AgedReport {
  AgedReport({
    required this.asOf,
    required this.debtors,
    required this.creditors,
    required this.sample,
  });

  final String asOf;
  final AgedTable debtors;
  final AgedTable creditors;
  final bool sample;

  static AgedTable _table(Map<String, dynamic> json, String key) {
    final v = json[key];
    return v is Map
        ? AgedTable.fromJson(Map<String, dynamic>.from(v))
        : AgedTable(rows: const [], buckets: const {}, totalPence: 0);
  }

  factory AgedReport.fromJson(Map<String, dynamic> json) => AgedReport(
        asOf: (json['as_of'] ?? '').toString(),
        debtors: _table(json, 'debtors'),
        creditors: _table(json, 'creditors'),
        sample: json['sample'] == true,
      );
}

/// One period of `GET /reports/vat` (oldest first on the wire).
class VatSummaryPeriod {
  VatSummaryPeriod({
    required this.period,
    required this.label,
    required this.vatOnSalesPence,
    required this.vatReclaimedPence,
    required this.netPence,
    required this.salesExPounds,
    required this.purchasesExPounds,
    required this.entries,
  });

  final String period;
  final String label;
  final int vatOnSalesPence; // box 1
  final int vatReclaimedPence; // box 4
  final int netPence; // box 3 − box 4: positive to pay
  final int salesExPounds; // box 6, whole pounds
  final int purchasesExPounds; // box 7, whole pounds
  final int entries;

  static VatSummaryPeriod fromJson(Map<String, dynamic> json) => VatSummaryPeriod(
        period: (json['period'] ?? '').toString(),
        label: (json['label'] ?? '').toString(),
        vatOnSalesPence: _pence(json['vat_on_sales_pence']),
        vatReclaimedPence: _pence(json['vat_reclaimed_pence']),
        netPence: _pence(json['net_vat_pence']),
        salesExPounds: _pence(json['sales_ex_vat_pounds']),
        purchasesExPounds: _pence(json['purchases_ex_vat_pounds']),
        entries: _pence(json['entries']),
      );
}

/// `GET /reports/vat`.
class VatSummary {
  VatSummary({
    required this.periods,
    required this.totalNetPence,
    required this.sample,
  });

  final List<VatSummaryPeriod> periods;
  final int totalNetPence;
  final bool sample;

  factory VatSummary.fromJson(Map<String, dynamic> json) => VatSummary(
        periods: [
          if (json['periods'] is List)
            for (final p in json['periods'] as List)
              if (p is Map) VatSummaryPeriod.fromJson(Map<String, dynamic>.from(p)),
        ],
        totalNetPence: _pence(json['total_net_vat_pence']),
        sample: json['sample'] == true,
      );
}

/// One calendar month of `GET /reports/trend` (oldest first on the wire).
class TrendMonth {
  TrendMonth({
    required this.month,
    required this.label,
    required this.salesPence,
    required this.purchasesPence,
    required this.netPence,
  });

  final String month; // "2026-10"
  final String label; // "Oct 2026"
  final int salesPence;
  final int purchasesPence; // cost of sales + overheads
  final int netPence;

  static TrendMonth fromJson(Map<String, dynamic> json) => TrendMonth(
        month: (json['month'] ?? '').toString(),
        label: (json['label'] ?? '').toString(),
        salesPence: _pence(json['sales_pence']),
        purchasesPence: _pence(json['purchases_pence']),
        netPence: _pence(json['net_pence']),
      );
}

/// `GET /reports/trend`.
class Trend {
  Trend({required this.months, required this.sample});

  final List<TrendMonth> months;
  final bool sample;

  factory Trend.fromJson(Map<String, dynamic> json) => Trend(
        months: [
          if (json['months'] is List)
            for (final m in json['months'] as List)
              if (m is Map) TrendMonth.fromJson(Map<String, dynamic>.from(m)),
        ],
        sample: json['sample'] == true,
      );
}

/// `POST /reports/export`: the spreadsheet saved in 07 Reports.
class ReportExport {
  ReportExport({
    required this.path,
    required this.name,
    required this.sample,
    required this.sheets,
  });

  final String path; // "07 Reports/2026-10-27-reports.xlsx"
  final String name; // the file name alone
  final bool sample;
  final List<String> sheets;

  factory ReportExport.fromJson(Map<String, dynamic> json) => ReportExport(
        path: (json['path'] ?? '').toString(),
        name: (json['name'] ?? '').toString(),
        sample: json['sample'] == true,
        sheets: [
          if (json['sheets'] is List) for (final s in json['sheets'] as List) s.toString(),
        ],
      );
}
