"""Where a set of books is: the country, its sales tax (VAT, GST or sales tax, and the rate) and the currency.

Accnomos was built for the UK and every UK book behaves as before: country "GB", VAT at the UK rates (20/5/0), pounds,
and the HMRC pages (VAT returns, payroll, MTD Income Tax, CIS). Books in any other country keep everything else —
Review, the assistant, files, bank, contacts, jobs, vehicles, invoices, goals, calendar, notes, reports and CSV
exports — with their own tax name and one standard rate, in their own currency, and none of the HMRC pages
(app/profile.py `features_for`, routes_books.require_uk).

Amounts stay integer minor units everywhere ("pence" is cents, paise, etc.): only the currencies here with two
decimal places can be chosen, so the ledger never needs to know which one it is.

The country list is ISO 3166-1 alpha-2 with English (UK) names; the web (apps/web/src/lib/region.ts) and Android
(apps/mobile/lib/region.dart) carry the same list and the same defaults.

Default standard rates were checked on 4 November 2026 (EU rates against hellotax.com/blog/vat-rates-in-europe:
EE 24% from 1 Jul 2025, RO 21% from 1 Aug 2025, SK 23% from 1 Jan 2025, FI 25.5% from 1 Sep 2024; BG uses the
euro from 1 Jan 2026). They only prefill the question "What percentage?": the user's own answer is what counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from app.books import Books

TaxName = Literal["VAT", "GST", "Sales tax", "None"]
TAX_NAMES: tuple[str, ...] = ("VAT", "GST", "Sales tax", "None")
UK = "GB"

COUNTRY_NAMES: dict[str, str] = {
    "AF": "Afghanistan",
    "AX": "Åland Islands",
    "AL": "Albania",
    "DZ": "Algeria",
    "AS": "American Samoa",
    "AD": "Andorra",
    "AO": "Angola",
    "AI": "Anguilla",
    "AQ": "Antarctica",
    "AG": "Antigua & Barbuda",
    "AR": "Argentina",
    "AM": "Armenia",
    "AW": "Aruba",
    "AU": "Australia",
    "AT": "Austria",
    "AZ": "Azerbaijan",
    "BS": "Bahamas",
    "BH": "Bahrain",
    "BD": "Bangladesh",
    "BB": "Barbados",
    "BY": "Belarus",
    "BE": "Belgium",
    "BZ": "Belize",
    "BJ": "Benin",
    "BM": "Bermuda",
    "BT": "Bhutan",
    "BO": "Bolivia",
    "BA": "Bosnia & Herzegovina",
    "BW": "Botswana",
    "BV": "Bouvet Island",
    "BR": "Brazil",
    "IO": "British Indian Ocean Territory",
    "VG": "British Virgin Islands",
    "BN": "Brunei",
    "BG": "Bulgaria",
    "BF": "Burkina Faso",
    "BI": "Burundi",
    "KH": "Cambodia",
    "CM": "Cameroon",
    "CA": "Canada",
    "CV": "Cape Verde",
    "BQ": "Caribbean Netherlands",
    "KY": "Cayman Islands",
    "CF": "Central African Republic",
    "TD": "Chad",
    "CL": "Chile",
    "CN": "China",
    "CX": "Christmas Island",
    "CC": "Cocos (Keeling) Islands",
    "CO": "Colombia",
    "KM": "Comoros",
    "CG": "Congo - Brazzaville",
    "CD": "Congo - Kinshasa",
    "CK": "Cook Islands",
    "CR": "Costa Rica",
    "CI": "Côte d’Ivoire",
    "HR": "Croatia",
    "CU": "Cuba",
    "CW": "Curaçao",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DK": "Denmark",
    "DJ": "Djibouti",
    "DM": "Dominica",
    "DO": "Dominican Republic",
    "EC": "Ecuador",
    "EG": "Egypt",
    "SV": "El Salvador",
    "GQ": "Equatorial Guinea",
    "ER": "Eritrea",
    "EE": "Estonia",
    "SZ": "Eswatini",
    "ET": "Ethiopia",
    "FK": "Falkland Islands",
    "FO": "Faroe Islands",
    "FJ": "Fiji",
    "FI": "Finland",
    "FR": "France",
    "GF": "French Guiana",
    "PF": "French Polynesia",
    "TF": "French Southern Territories",
    "GA": "Gabon",
    "GM": "Gambia",
    "GE": "Georgia",
    "DE": "Germany",
    "GH": "Ghana",
    "GI": "Gibraltar",
    "GR": "Greece",
    "GL": "Greenland",
    "GD": "Grenada",
    "GP": "Guadeloupe",
    "GU": "Guam",
    "GT": "Guatemala",
    "GG": "Guernsey",
    "GN": "Guinea",
    "GW": "Guinea-Bissau",
    "GY": "Guyana",
    "HT": "Haiti",
    "HM": "Heard & McDonald Islands",
    "HN": "Honduras",
    "HK": "Hong Kong SAR China",
    "HU": "Hungary",
    "IS": "Iceland",
    "IN": "India",
    "ID": "Indonesia",
    "IR": "Iran",
    "IQ": "Iraq",
    "IE": "Ireland",
    "IM": "Isle of Man",
    "IL": "Israel",
    "IT": "Italy",
    "JM": "Jamaica",
    "JP": "Japan",
    "JE": "Jersey",
    "JO": "Jordan",
    "KZ": "Kazakhstan",
    "KE": "Kenya",
    "KI": "Kiribati",
    "KW": "Kuwait",
    "KG": "Kyrgyzstan",
    "LA": "Laos",
    "LV": "Latvia",
    "LB": "Lebanon",
    "LS": "Lesotho",
    "LR": "Liberia",
    "LY": "Libya",
    "LI": "Liechtenstein",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "MO": "Macao SAR China",
    "MG": "Madagascar",
    "MW": "Malawi",
    "MY": "Malaysia",
    "MV": "Maldives",
    "ML": "Mali",
    "MT": "Malta",
    "MH": "Marshall Islands",
    "MQ": "Martinique",
    "MR": "Mauritania",
    "MU": "Mauritius",
    "YT": "Mayotte",
    "MX": "Mexico",
    "FM": "Micronesia",
    "MD": "Moldova",
    "MC": "Monaco",
    "MN": "Mongolia",
    "ME": "Montenegro",
    "MS": "Montserrat",
    "MA": "Morocco",
    "MZ": "Mozambique",
    "MM": "Myanmar (Burma)",
    "NA": "Namibia",
    "NR": "Nauru",
    "NP": "Nepal",
    "NL": "Netherlands",
    "NC": "New Caledonia",
    "NZ": "New Zealand",
    "NI": "Nicaragua",
    "NE": "Niger",
    "NG": "Nigeria",
    "NU": "Niue",
    "NF": "Norfolk Island",
    "KP": "North Korea",
    "MK": "North Macedonia",
    "MP": "Northern Mariana Islands",
    "NO": "Norway",
    "OM": "Oman",
    "PK": "Pakistan",
    "PW": "Palau",
    "PS": "Palestinian Territories",
    "PA": "Panama",
    "PG": "Papua New Guinea",
    "PY": "Paraguay",
    "PE": "Peru",
    "PH": "Philippines",
    "PN": "Pitcairn Islands",
    "PL": "Poland",
    "PT": "Portugal",
    "PR": "Puerto Rico",
    "QA": "Qatar",
    "RE": "Réunion",
    "RO": "Romania",
    "RU": "Russia",
    "RW": "Rwanda",
    "WS": "Samoa",
    "SM": "San Marino",
    "ST": "São Tomé & Príncipe",
    "SA": "Saudi Arabia",
    "SN": "Senegal",
    "RS": "Serbia",
    "SC": "Seychelles",
    "SL": "Sierra Leone",
    "SG": "Singapore",
    "SX": "Sint Maarten",
    "SK": "Slovakia",
    "SI": "Slovenia",
    "SB": "Solomon Islands",
    "SO": "Somalia",
    "ZA": "South Africa",
    "GS": "South Georgia & South Sandwich Islands",
    "KR": "South Korea",
    "SS": "South Sudan",
    "ES": "Spain",
    "LK": "Sri Lanka",
    "BL": "St Barthélemy",
    "SH": "St Helena",
    "KN": "St Kitts & Nevis",
    "LC": "St Lucia",
    "MF": "St Martin",
    "PM": "St Pierre & Miquelon",
    "VC": "St Vincent & the Grenadines",
    "SD": "Sudan",
    "SR": "Suriname",
    "SJ": "Svalbard & Jan Mayen",
    "SE": "Sweden",
    "CH": "Switzerland",
    "SY": "Syria",
    "TW": "Taiwan",
    "TJ": "Tajikistan",
    "TZ": "Tanzania",
    "TH": "Thailand",
    "TL": "Timor-Leste",
    "TG": "Togo",
    "TK": "Tokelau",
    "TO": "Tonga",
    "TT": "Trinidad & Tobago",
    "TN": "Tunisia",
    "TR": "Türkiye",
    "TM": "Turkmenistan",
    "TC": "Turks & Caicos Islands",
    "TV": "Tuvalu",
    "UG": "Uganda",
    "UA": "Ukraine",
    "AE": "United Arab Emirates",
    "GB": "United Kingdom",
    "US": "United States",
    "UY": "Uruguay",
    "UM": "US Outlying Islands",
    "VI": "US Virgin Islands",
    "UZ": "Uzbekistan",
    "VU": "Vanuatu",
    "VA": "Vatican City",
    "VE": "Venezuela",
    "VN": "Vietnam",
    "WF": "Wallis & Futuna",
    "EH": "Western Sahara",
    "YE": "Yemen",
    "ZM": "Zambia",
    "ZW": "Zimbabwe",
}

#: Currencies that can be chosen: ISO 4217 codes with two decimal places (amounts are kept in hundredths).
CURRENCIES: dict[str, str] = {
    "GBP": "Pound sterling",
    "EUR": "Euro",
    "USD": "US dollar",
    "CAD": "Canadian dollar",
    "AUD": "Australian dollar",
    "NZD": "New Zealand dollar",
    "INR": "Indian rupee",
    "PKR": "Pakistani rupee",
    "BDT": "Bangladeshi taka",
    "LKR": "Sri Lankan rupee",
    "AED": "UAE dirham",
    "SAR": "Saudi riyal",
    "QAR": "Qatari riyal",
    "SGD": "Singapore dollar",
    "MYR": "Malaysian ringgit",
    "HKD": "Hong Kong dollar",
    "PHP": "Philippine peso",
    "THB": "Thai baht",
    "ZAR": "South African rand",
    "NGN": "Nigerian naira",
    "KES": "Kenyan shilling",
    "GHS": "Ghanaian cedi",
    "EGP": "Egyptian pound",
    "MAD": "Moroccan dirham",
    "TRY": "Turkish lira",
    "CHF": "Swiss franc",
    "NOK": "Norwegian krone",
    "SEK": "Swedish krona",
    "DKK": "Danish krone",
    "PLN": "Polish złoty",
    "CZK": "Czech koruna",
    "HUF": "Hungarian forint",
    "RON": "Romanian leu",
    "MXN": "Mexican peso",
    "BRL": "Brazilian real",
}

EURO: tuple[str, ...] = (
    "AT",
    "BE",
    "BG",
    "HR",
    "CY",
    "EE",
    "FI",
    "FR",
    "DE",
    "GR",
    "IE",
    "IT",
    "LV",
    "LT",
    "LU",
    "MT",
    "NL",
    "PT",
    "SK",
    "SI",
    "ES",
    "AD",
    "MC",
    "SM",
    "VA",
    "ME",
)

#: Country -> its currency, where the app knows it; anywhere else the user picks one.
DEFAULT_CURRENCY: dict[str, str] = {
    **dict.fromkeys(EURO, "EUR"),
    "GB": "GBP",
    "US": "USD",
    "CA": "CAD",
    "AU": "AUD",
    "NZ": "NZD",
    "IN": "INR",
    "PK": "PKR",
    "BD": "BDT",
    "LK": "LKR",
    "AE": "AED",
    "SA": "SAR",
    "QA": "QAR",
    "SG": "SGD",
    "MY": "MYR",
    "HK": "HKD",
    "PH": "PHP",
    "TH": "THB",
    "ZA": "ZAR",
    "NG": "NGN",
    "KE": "KES",
    "GH": "GHS",
    "EG": "EGP",
    "MA": "MAD",
    "TR": "TRY",
    "CH": "CHF",
    "LI": "CHF",
    "NO": "NOK",
    "SE": "SEK",
    "DK": "DKK",
    "PL": "PLN",
    "CZ": "CZK",
    "HU": "HUF",
    "RO": "RON",
    "MX": "MXN",
    "BR": "BRL",
}

#: Country -> (tax name, standard rate %) to prefill; elsewhere "Sales tax" and a rate the user enters.
DEFAULT_TAX: dict[str, tuple[str, float]] = {
    "AT": ("VAT", 20), "BE": ("VAT", 21), "BG": ("VAT", 20), "HR": ("VAT", 25), "CY": ("VAT", 19),
    "CZ": ("VAT", 21), "DK": ("VAT", 25), "EE": ("VAT", 24), "FI": ("VAT", 25.5), "FR": ("VAT", 20),
    "DE": ("VAT", 19), "GR": ("VAT", 24), "HU": ("VAT", 27), "IE": ("VAT", 23), "IT": ("VAT", 22),
    "LV": ("VAT", 21), "LT": ("VAT", 21), "LU": ("VAT", 17), "MT": ("VAT", 18), "NL": ("VAT", 21),
    "PL": ("VAT", 23), "PT": ("VAT", 23), "RO": ("VAT", 21), "SK": ("VAT", 23), "SI": ("VAT", 22),
    "ES": ("VAT", 21), "SE": ("VAT", 25),
    "AU": ("GST", 10), "NZ": ("GST", 15), "IN": ("GST", 18), "SG": ("GST", 9), "CA": ("GST", 5),
    "PK": ("Sales tax", 18), "MY": ("Sales tax", 8), "US": ("Sales tax", 0),
    "AE": ("VAT", 5), "SA": ("VAT", 15), "ZA": ("VAT", 15),
}  # fmt: skip


def country_name(code: str) -> str:
    return COUNTRY_NAMES.get(code, code)


def default_currency(country: str) -> str | None:
    return DEFAULT_CURRENCY.get(country)


def default_tax(country: str) -> tuple[str, float]:
    return DEFAULT_TAX.get(country, ("Sales tax", 0))


@dataclass(frozen=True)
class TaxRules:
    """What the checks, the journal and invoices need to know about the books' country. UK_RULES unless the
    profile says another country."""

    country: str = UK
    currency: str = "GBP"
    tax_name: str = "VAT"  # "None": the business charges no sales tax
    rate: float = 20.0  # the one standard rate outside the UK; the UK keeps 20/5/0

    @property
    def uk(self) -> bool:
        return self.country == UK

    @property
    def charges_tax(self) -> bool:
        return self.uk or (self.tax_name != "None" and self.rate > 0)

    @property
    def label(self) -> str:
        """ "VAT", "GST", "Sales tax"; "Tax" for a business that charges none."""
        return "Tax" if self.tax_name == "None" else self.tax_name

    def sales_rates(self) -> dict[str, float]:
        """Invoice VAT codes to rates: the UK's own, or the user's one rate for standard and reduced lines."""
        if self.uk:
            return {"S": 20, "R": 5, "Z": 0, "E": 0, "O": 0}
        r = self.rate if self.charges_tax else 0
        return {"S": r, "R": r, "Z": 0, "E": 0, "O": 0}


UK_RULES = TaxRules()


def extraction_hint(rules: TaxRules) -> str | None:
    """One sentence for the reading model about books kept outside the UK (None for UK books: the prompt as before)."""
    if rules.uk:
        return None
    tax = f"{rules.tax_name} at {rules.rate:g}%" if rules.charges_tax else "no sales tax"
    return (
        f"These books are kept in {country_name(rules.country)} in {rules.currency}: report a bare currency sign as "
        f"{rules.currency} unless the document says otherwise, and read any {rules.label} shown as the vat fields "
        f"(the business usually sees {tax})."
    )


def rules_from_settings(settings: dict[str, Any] | None) -> TaxRules:
    """TaxRules from a profile's settings (app/profile.py); no `country` (every UK book): UK_RULES."""
    s = settings or {}
    country = str(s.get("country") or UK)
    if country == UK:
        return UK_RULES
    tax = s.get("sales_tax") or {}
    name, rate = default_tax(country)
    return TaxRules(
        country=country,
        currency=str(s.get("currency") or default_currency(country) or "USD"),
        tax_name=str(tax.get("name") or name),
        rate=float(given) if (given := tax.get("rate_percent")) is not None else float(rate),
    )


async def rules_for(books: Books) -> TaxRules:
    """The books' TaxRules, read from profile.json leniently: an unreadable profile is a UK book, as everywhere."""
    from app import profile as profile_mod

    try:
        p = await profile_mod.load(books)
    except Exception:  # noqa: BLE001 - a broken profile.json must never stop a scan or an approval
        return UK_RULES
    return rules_from_settings(p.settings)


def format_money(pence: int, currency: str = "GBP") -> str:
    """'£1,234.50', '€1,234.50', 'A$1,234.50' from minor units, exactly (no floats)."""
    sign = "-" if pence < 0 else ""
    whole, minor = divmod(abs(pence), 100)
    return f"{sign}{currency_symbol(currency)}{whole:,}.{minor:02d}"


SYMBOLS: dict[str, str] = {
    "GBP": "£", "EUR": "€", "USD": "$", "CAD": "CA$", "AUD": "A$", "NZD": "NZ$", "INR": "₹", "PKR": "Rs ",
    "SGD": "S$", "HKD": "HK$", "MYR": "RM", "ZAR": "R", "PHP": "₱", "THB": "฿", "NGN": "₦", "TRY": "₺",
    "MXN": "MX$", "BRL": "R$",
}  # fmt: skip


def currency_symbol(currency: str) -> str:
    return SYMBOLS.get(currency, f"{currency} ")
