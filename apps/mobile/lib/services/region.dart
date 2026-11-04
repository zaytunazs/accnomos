import 'package:flutter/foundation.dart';

/// Where the books are kept (services/runtime/app/region.py and the web's
/// lib/region.ts, the same list and defaults): the country, the tax the
/// business charges (VAT, GST or sales tax, at one rate) and the currency.
///
/// UK books are the default and behave as always. Books elsewhere have no
/// HMRC pages (the runtime drops `vat`, `payroll` and `self_employment` from
/// their features, so More and Home hide them) and show money in their own
/// currency ([formatMoneyPence] reads [BooksRegion.current]).
@immutable
class BooksRegion {
  const BooksRegion({
    this.country = 'GB',
    this.countryName = 'United Kingdom',
    this.currency = 'GBP',
    this.taxName = 'VAT',
    this.taxLabel = 'VAT',
    this.taxRate = 20,
  });

  final String country;
  final String countryName;
  final String currency;

  /// `VAT`, `GST`, `Sales tax` or `None`.
  final String taxName;

  /// What the screens call it (`Tax` for a business that charges none).
  final String taxLabel;
  final num taxRate;

  bool get uk => country == 'GB';

  /// "10", "8.875": the rate without a trailing ".0".
  String get rateText =>
      taxRate == taxRate.roundToDouble() ? taxRate.toInt().toString() : '$taxRate';

  /// `£`, `€`, `A$`; the code and a space for a currency with no short sign.
  String get sign => currencySign(currency);

  static const ukBooks = BooksRegion();

  /// GET /profile's `region`; anything missing or unreadable is UK books.
  factory BooksRegion.fromJson(Object? raw) {
    if (raw is! Map) return ukBooks;
    final country = '${raw['country'] ?? 'GB'}';
    if (country == 'GB') return ukBooks;
    return BooksRegion(
      country: country,
      countryName: '${raw['country_name'] ?? countryNameOf(country)}',
      currency: '${raw['currency'] ?? defaultCurrency(country) ?? 'USD'}',
      taxName: '${raw['tax_name'] ?? 'Sales tax'}',
      taxLabel: '${raw['tax_label'] ?? raw['tax_name'] ?? 'Tax'}',
      taxRate: raw['tax_rate_percent'] is num ? raw['tax_rate_percent'] as num : 0,
    );
  }

  /// The current books' region, set whenever the profile is read
  /// (AppMode.refresh, Settings › Business details).
  static final ValueNotifier<BooksRegion> current = ValueNotifier(ukBooks);
}

const taxNames = ['VAT', 'GST', 'Sales tax', 'None'];

/// ISO 3166-1 alpha-2 code and English (UK) name, by name.
const countries = <(String, String)>[
  ('AF', 'Afghanistan'),
  ('AX', 'Åland Islands'),
  ('AL', 'Albania'),
  ('DZ', 'Algeria'),
  ('AS', 'American Samoa'),
  ('AD', 'Andorra'),
  ('AO', 'Angola'),
  ('AI', 'Anguilla'),
  ('AQ', 'Antarctica'),
  ('AG', 'Antigua & Barbuda'),
  ('AR', 'Argentina'),
  ('AM', 'Armenia'),
  ('AW', 'Aruba'),
  ('AU', 'Australia'),
  ('AT', 'Austria'),
  ('AZ', 'Azerbaijan'),
  ('BS', 'Bahamas'),
  ('BH', 'Bahrain'),
  ('BD', 'Bangladesh'),
  ('BB', 'Barbados'),
  ('BY', 'Belarus'),
  ('BE', 'Belgium'),
  ('BZ', 'Belize'),
  ('BJ', 'Benin'),
  ('BM', 'Bermuda'),
  ('BT', 'Bhutan'),
  ('BO', 'Bolivia'),
  ('BA', 'Bosnia & Herzegovina'),
  ('BW', 'Botswana'),
  ('BV', 'Bouvet Island'),
  ('BR', 'Brazil'),
  ('IO', 'British Indian Ocean Territory'),
  ('VG', 'British Virgin Islands'),
  ('BN', 'Brunei'),
  ('BG', 'Bulgaria'),
  ('BF', 'Burkina Faso'),
  ('BI', 'Burundi'),
  ('KH', 'Cambodia'),
  ('CM', 'Cameroon'),
  ('CA', 'Canada'),
  ('CV', 'Cape Verde'),
  ('BQ', 'Caribbean Netherlands'),
  ('KY', 'Cayman Islands'),
  ('CF', 'Central African Republic'),
  ('TD', 'Chad'),
  ('CL', 'Chile'),
  ('CN', 'China'),
  ('CX', 'Christmas Island'),
  ('CC', 'Cocos (Keeling) Islands'),
  ('CO', 'Colombia'),
  ('KM', 'Comoros'),
  ('CG', 'Congo - Brazzaville'),
  ('CD', 'Congo - Kinshasa'),
  ('CK', 'Cook Islands'),
  ('CR', 'Costa Rica'),
  ('CI', 'Côte d’Ivoire'),
  ('HR', 'Croatia'),
  ('CU', 'Cuba'),
  ('CW', 'Curaçao'),
  ('CY', 'Cyprus'),
  ('CZ', 'Czechia'),
  ('DK', 'Denmark'),
  ('DJ', 'Djibouti'),
  ('DM', 'Dominica'),
  ('DO', 'Dominican Republic'),
  ('EC', 'Ecuador'),
  ('EG', 'Egypt'),
  ('SV', 'El Salvador'),
  ('GQ', 'Equatorial Guinea'),
  ('ER', 'Eritrea'),
  ('EE', 'Estonia'),
  ('SZ', 'Eswatini'),
  ('ET', 'Ethiopia'),
  ('FK', 'Falkland Islands'),
  ('FO', 'Faroe Islands'),
  ('FJ', 'Fiji'),
  ('FI', 'Finland'),
  ('FR', 'France'),
  ('GF', 'French Guiana'),
  ('PF', 'French Polynesia'),
  ('TF', 'French Southern Territories'),
  ('GA', 'Gabon'),
  ('GM', 'Gambia'),
  ('GE', 'Georgia'),
  ('DE', 'Germany'),
  ('GH', 'Ghana'),
  ('GI', 'Gibraltar'),
  ('GR', 'Greece'),
  ('GL', 'Greenland'),
  ('GD', 'Grenada'),
  ('GP', 'Guadeloupe'),
  ('GU', 'Guam'),
  ('GT', 'Guatemala'),
  ('GG', 'Guernsey'),
  ('GN', 'Guinea'),
  ('GW', 'Guinea-Bissau'),
  ('GY', 'Guyana'),
  ('HT', 'Haiti'),
  ('HM', 'Heard & McDonald Islands'),
  ('HN', 'Honduras'),
  ('HK', 'Hong Kong SAR China'),
  ('HU', 'Hungary'),
  ('IS', 'Iceland'),
  ('IN', 'India'),
  ('ID', 'Indonesia'),
  ('IR', 'Iran'),
  ('IQ', 'Iraq'),
  ('IE', 'Ireland'),
  ('IM', 'Isle of Man'),
  ('IL', 'Israel'),
  ('IT', 'Italy'),
  ('JM', 'Jamaica'),
  ('JP', 'Japan'),
  ('JE', 'Jersey'),
  ('JO', 'Jordan'),
  ('KZ', 'Kazakhstan'),
  ('KE', 'Kenya'),
  ('KI', 'Kiribati'),
  ('KW', 'Kuwait'),
  ('KG', 'Kyrgyzstan'),
  ('LA', 'Laos'),
  ('LV', 'Latvia'),
  ('LB', 'Lebanon'),
  ('LS', 'Lesotho'),
  ('LR', 'Liberia'),
  ('LY', 'Libya'),
  ('LI', 'Liechtenstein'),
  ('LT', 'Lithuania'),
  ('LU', 'Luxembourg'),
  ('MO', 'Macao SAR China'),
  ('MG', 'Madagascar'),
  ('MW', 'Malawi'),
  ('MY', 'Malaysia'),
  ('MV', 'Maldives'),
  ('ML', 'Mali'),
  ('MT', 'Malta'),
  ('MH', 'Marshall Islands'),
  ('MQ', 'Martinique'),
  ('MR', 'Mauritania'),
  ('MU', 'Mauritius'),
  ('YT', 'Mayotte'),
  ('MX', 'Mexico'),
  ('FM', 'Micronesia'),
  ('MD', 'Moldova'),
  ('MC', 'Monaco'),
  ('MN', 'Mongolia'),
  ('ME', 'Montenegro'),
  ('MS', 'Montserrat'),
  ('MA', 'Morocco'),
  ('MZ', 'Mozambique'),
  ('MM', 'Myanmar (Burma)'),
  ('NA', 'Namibia'),
  ('NR', 'Nauru'),
  ('NP', 'Nepal'),
  ('NL', 'Netherlands'),
  ('NC', 'New Caledonia'),
  ('NZ', 'New Zealand'),
  ('NI', 'Nicaragua'),
  ('NE', 'Niger'),
  ('NG', 'Nigeria'),
  ('NU', 'Niue'),
  ('NF', 'Norfolk Island'),
  ('KP', 'North Korea'),
  ('MK', 'North Macedonia'),
  ('MP', 'Northern Mariana Islands'),
  ('NO', 'Norway'),
  ('OM', 'Oman'),
  ('PK', 'Pakistan'),
  ('PW', 'Palau'),
  ('PS', 'Palestinian Territories'),
  ('PA', 'Panama'),
  ('PG', 'Papua New Guinea'),
  ('PY', 'Paraguay'),
  ('PE', 'Peru'),
  ('PH', 'Philippines'),
  ('PN', 'Pitcairn Islands'),
  ('PL', 'Poland'),
  ('PT', 'Portugal'),
  ('PR', 'Puerto Rico'),
  ('QA', 'Qatar'),
  ('RE', 'Réunion'),
  ('RO', 'Romania'),
  ('RU', 'Russia'),
  ('RW', 'Rwanda'),
  ('WS', 'Samoa'),
  ('SM', 'San Marino'),
  ('ST', 'São Tomé & Príncipe'),
  ('SA', 'Saudi Arabia'),
  ('SN', 'Senegal'),
  ('RS', 'Serbia'),
  ('SC', 'Seychelles'),
  ('SL', 'Sierra Leone'),
  ('SG', 'Singapore'),
  ('SX', 'Sint Maarten'),
  ('SK', 'Slovakia'),
  ('SI', 'Slovenia'),
  ('SB', 'Solomon Islands'),
  ('SO', 'Somalia'),
  ('ZA', 'South Africa'),
  ('GS', 'South Georgia & South Sandwich Islands'),
  ('KR', 'South Korea'),
  ('SS', 'South Sudan'),
  ('ES', 'Spain'),
  ('LK', 'Sri Lanka'),
  ('BL', 'St Barthélemy'),
  ('SH', 'St Helena'),
  ('KN', 'St Kitts & Nevis'),
  ('LC', 'St Lucia'),
  ('MF', 'St Martin'),
  ('PM', 'St Pierre & Miquelon'),
  ('VC', 'St Vincent & the Grenadines'),
  ('SD', 'Sudan'),
  ('SR', 'Suriname'),
  ('SJ', 'Svalbard & Jan Mayen'),
  ('SE', 'Sweden'),
  ('CH', 'Switzerland'),
  ('SY', 'Syria'),
  ('TW', 'Taiwan'),
  ('TJ', 'Tajikistan'),
  ('TZ', 'Tanzania'),
  ('TH', 'Thailand'),
  ('TL', 'Timor-Leste'),
  ('TG', 'Togo'),
  ('TK', 'Tokelau'),
  ('TO', 'Tonga'),
  ('TT', 'Trinidad & Tobago'),
  ('TN', 'Tunisia'),
  ('TR', 'Türkiye'),
  ('TM', 'Turkmenistan'),
  ('TC', 'Turks & Caicos Islands'),
  ('TV', 'Tuvalu'),
  ('UG', 'Uganda'),
  ('UA', 'Ukraine'),
  ('AE', 'United Arab Emirates'),
  ('GB', 'United Kingdom'),
  ('US', 'United States'),
  ('UY', 'Uruguay'),
  ('UM', 'US Outlying Islands'),
  ('VI', 'US Virgin Islands'),
  ('UZ', 'Uzbekistan'),
  ('VU', 'Vanuatu'),
  ('VA', 'Vatican City'),
  ('VE', 'Venezuela'),
  ('VN', 'Vietnam'),
  ('WF', 'Wallis & Futuna'),
  ('EH', 'Western Sahara'),
  ('YE', 'Yemen'),
  ('ZM', 'Zambia'),
  ('ZW', 'Zimbabwe'),
];

const currencies = <(String, String)>[
  ('GBP', 'Pound sterling'), ('EUR', 'Euro'), ('USD', 'US dollar'),
  ('CAD', 'Canadian dollar'), ('AUD', 'Australian dollar'),
  ('NZD', 'New Zealand dollar'), ('INR', 'Indian rupee'),
  ('PKR', 'Pakistani rupee'), ('BDT', 'Bangladeshi taka'),
  ('LKR', 'Sri Lankan rupee'), ('AED', 'UAE dirham'), ('SAR', 'Saudi riyal'),
  ('QAR', 'Qatari riyal'), ('SGD', 'Singapore dollar'),
  ('MYR', 'Malaysian ringgit'), ('HKD', 'Hong Kong dollar'),
  ('PHP', 'Philippine peso'), ('THB', 'Thai baht'),
  ('ZAR', 'South African rand'), ('NGN', 'Nigerian naira'),
  ('KES', 'Kenyan shilling'), ('GHS', 'Ghanaian cedi'),
  ('EGP', 'Egyptian pound'), ('MAD', 'Moroccan dirham'),
  ('TRY', 'Turkish lira'), ('CHF', 'Swiss franc'), ('NOK', 'Norwegian krone'),
  ('SEK', 'Swedish krona'), ('DKK', 'Danish krone'), ('PLN', 'Polish złoty'),
  ('CZK', 'Czech koruna'), ('HUF', 'Hungarian forint'), ('RON', 'Romanian leu'),
  ('MXN', 'Mexican peso'), ('BRL', 'Brazilian real'),
];

const _euro = [
  'AT', 'BE', 'BG', 'HR', 'CY', 'EE', 'FI', 'FR', 'DE', 'GR', 'IE', 'IT', 'LV',
  'LT', 'LU', 'MT', 'NL', 'PT', 'SK', 'SI', 'ES', 'AD', 'MC', 'SM', 'VA', 'ME',
];

const _currencyOf = <String, String>{
  'GB': 'GBP', 'US': 'USD', 'CA': 'CAD', 'AU': 'AUD', 'NZ': 'NZD', 'IN': 'INR',
  'PK': 'PKR', 'BD': 'BDT', 'LK': 'LKR', 'AE': 'AED', 'SA': 'SAR', 'QA': 'QAR',
  'SG': 'SGD', 'MY': 'MYR', 'HK': 'HKD', 'PH': 'PHP', 'TH': 'THB', 'ZA': 'ZAR',
  'NG': 'NGN', 'KE': 'KES', 'GH': 'GHS', 'EG': 'EGP', 'MA': 'MAD', 'TR': 'TRY',
  'CH': 'CHF', 'LI': 'CHF', 'NO': 'NOK', 'SE': 'SEK', 'DK': 'DKK', 'PL': 'PLN',
  'CZ': 'CZK', 'HU': 'HUF', 'RO': 'RON', 'MX': 'MXN', 'BR': 'BRL',
};

/// Typical standard rate to prefill "What percentage?" (checked 4 Nov 2026).
const _taxOf = <String, (String, num)>{
  'AT': ('VAT', 20), 'BE': ('VAT', 21), 'BG': ('VAT', 20), 'HR': ('VAT', 25),
  'CY': ('VAT', 19), 'CZ': ('VAT', 21), 'DK': ('VAT', 25), 'EE': ('VAT', 24),
  'FI': ('VAT', 25.5), 'FR': ('VAT', 20), 'DE': ('VAT', 19), 'GR': ('VAT', 24),
  'HU': ('VAT', 27), 'IE': ('VAT', 23), 'IT': ('VAT', 22), 'LV': ('VAT', 21),
  'LT': ('VAT', 21), 'LU': ('VAT', 17), 'MT': ('VAT', 18), 'NL': ('VAT', 21),
  'PL': ('VAT', 23), 'PT': ('VAT', 23), 'RO': ('VAT', 21), 'SK': ('VAT', 23),
  'SI': ('VAT', 22), 'ES': ('VAT', 21), 'SE': ('VAT', 25),
  'AU': ('GST', 10), 'NZ': ('GST', 15), 'IN': ('GST', 18), 'SG': ('GST', 9),
  'CA': ('GST', 5), 'PK': ('Sales tax', 18), 'MY': ('Sales tax', 8),
  'US': ('Sales tax', 0), 'AE': ('VAT', 5), 'SA': ('VAT', 15), 'ZA': ('VAT', 15),
};

const _signs = <String, String>{
  'GBP': '£', 'EUR': '€', 'USD': r'$', 'CAD': r'CA$', 'AUD': r'A$',
  'NZD': r'NZ$', 'INR': '₹', 'PKR': 'Rs ', 'SGD': r'S$', 'HKD': r'HK$',
  'MYR': 'RM', 'ZAR': 'R', 'PHP': '₱', 'THB': '฿', 'NGN': '₦', 'TRY': '₺',
  'MXN': r'MX$', 'BRL': r'R$',
};

String currencySign(String code) => _signs[code] ?? '$code ';

String countryNameOf(String code) {
  for (final (c, n) in countries) {
    if (c == code) return n;
  }
  return code;
}

/// The country's currency, or null when the user has to pick one.
String? defaultCurrency(String country) =>
    _euro.contains(country) ? 'EUR' : _currencyOf[country];

/// The country's usual tax and rate; elsewhere "Sales tax" at a rate the
/// user enters.
(String, num) defaultTax(String country) =>
    _taxOf[country] ?? ('Sales tax', 0);
