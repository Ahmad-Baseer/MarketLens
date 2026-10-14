import math

import pytest

from mbf.extract import statements as S


# ------------------------------------------------------------------ numbers
@pytest.mark.parametrize("tok,expected", [
    ("1,234", 1234.0),
    ("(1,234)", -1234.0),
    ("948,399,800", 948399800.0),
    ("(7.33)", -7.33),
    ("6.59", 6.59),
    ("-", 0.0),
    ("–", 0.0),
    ("-1,500", -1500.0),
    ("1.240.075.372", 1240075372.0),     # OCR / text layer with dots as separators
    ("(1,234", -1234.0),                 # a bracket lost
    ("C1,234)", -1234.0),                # '(' read as 'C'
])
def test_parse_number(tok, expected):
    assert S.parse_number(tok) == pytest.approx(expected)


@pytest.mark.parametrize("tok", ["N/A", "Note", "12.5%", "", "Rs.10", "2,280,346,4~3"])
def test_parse_number_rejects(tok):
    assert S.parse_number(tok) is None


def test_clean_ocr_number():
    assert S.clean_ocr_number("[27,547,423]") == "(27,547,423)"
    assert S.clean_ocr_number("(B8,113,415)") == "(88,113,415)"
    assert S.clean_ocr_number("80.331") == "80,331"       # comma read as a dot
    assert S.clean_ocr_number("1O,512") == "10,512"
    assert S.clean_ocr_number("Sales") == "Sales"          # labels untouched
    assert S.clean_ocr_number("0.86") == "0.86"            # EPS keeps its decimals


def test_fragments_rejoined():
    w = S.Word
    line = S.group_lines([w(10, 60, 0, 8, "Cost"), w(400, 403, 0, 8, "("), w(405, 450, 0, 8, "961,657,992)"),
                          w(480, 485, 0, 8, "1"), w(487, 520, 0, 8, ",098,933")])[0]
    assert [x.text for x in line] == ["Cost", "(961,657,992)", "1,098,933"]


def test_decode_cid():
    assert S.decode_cid("(cid:72)(cid:65)(cid:70)(cid:32)(cid:52)(cid:44)") == "HAF 4,"


# ------------------------------------------------------------------ units
@pytest.mark.parametrize("text,factor", [
    ("Note (Rupees in '000)", 1.0),
    ("-----(Rupees in ‘000)-----", 1.0),
    ("Rs. '000", 1.0),
    ("(Rupees in thousand)", 1.0),
    ("Amounts in PKR 000", 1.0),
    ("Rupees in million", 1000.0),
    ("(Rs. in Million)", 1000.0),
    ("2020 2019\nNote Rupees Rupees", 0.001),
    ("------- (Rupees) -------", 0.001),
])
def test_detect_unit(text, factor):
    assert S.detect_unit(text)[0] == factor


def test_detect_unit_ignores_par_value():
    assert S.detect_unit("100,000,000 ordinary shares of Rs.10 each") == (None, "")


def test_check_units_fixes_pl_off_by_1000():
    """P&L read as full rupees while it is in thousands: EPS gives it away."""
    rows = [{"field_key": "share_cap", "value_thousands": 840_000.0},
            {"field_key": "pat", "value_thousands": 219.902},       # really 219,902 thousand
            {"field_key": "sales", "value_thousands": 4_449.8},
            {"field_key": "eps", "value_thousands": 2.62}]
    assert S.check_units(rows) != ""
    v = {r["field_key"]: r["value_thousands"] for r in rows}
    assert v["pat"] == pytest.approx(219_902) and v["sales"] == pytest.approx(4_449_800)
    assert v["eps"] == 2.62 and v["share_cap"] == 840_000
    ok = [{"field_key": "share_cap", "value_thousands": 840_000.0},
          {"field_key": "pat", "value_thousands": 219_902.0}, {"field_key": "eps", "value_thousands": 2.62}]
    assert S.check_units(ok) == ""


def test_guess_unit():
    assert S.guess_unit([948_399_800, 4_906_148_748, 6_763_828])[0] == 0.001
    assert S.guess_unit([948_400, 4_906_149, 6_764])[0] == 1.0


# ------------------------------------------------------------------ labels
@pytest.mark.parametrize("label,section,key", [
    ("Total equity", "equity", "equity"),
    ("Shareholders' equity", None, "equity"),
    ("TOTAL EQUITY AND LIABILITIES", None, "eq_liab"),
    ("Issued, subscribed and paid-up capital", "equity", "share_cap"),
    ("Share capital", "equity", "share_cap"),
    ("Authorised share capital", "equity", None),
    ("Total assets", None, "assets"),
    ("Total non-current liabilities", None, "nc_liabilities"),
    ("Cash and bank balances", "c_assets", "cabb"),
    ("Cash and cash equivalents", "c_assets", "cabb"),
    ("Short term borrowings - secured", "c_liabilities", "st_borr"),
    ("Running finance under mark-up arrangements", "c_liabilities", "st_borr"),
    ("Mark-up accrued on short term borrowings", "c_liabilities", None),
    ("Long-term financing - secured", "nc_liabilities", "lt_debt"),
    ("Current portion of long term financing", "c_liabilities", None),
    ("Long term loans and advances", "nc_assets", None),
    ("Cash and bankbalanccs", "c_assets", "cabb"),          # OCR misspelling, fuzzy match
])
def test_map_label_bs(label, section, key):
    assert S.map_label(label, "bs", section) == key


@pytest.mark.parametrize("label,key", [
    ("Sales - net", "sales"),
    ("Revenue from contracts with customers", "sales"),
    ("Turnover - net", "sales"),
    ("Cost of sales", None),
    ("Sales tax", None),
    ("(Loss)/profit before taxation", "pbt"),
    ("Profit / (loss) before levies and income tax", "pbt"),
    ("Profit after taxation", "pat"),
    ("Net loss for the period", "pat"),
    ("Total comprehensive income for the year", None),
    ("Income tax for the year", None),
    ("Earnings / (loss) per share - basic and diluted", "eps"),
])
def test_map_label_pl(label, key):
    assert S.map_label(label, "pl") == key


@pytest.mark.parametrize("label,section", [
    ("NON-CURRENT LIABILITIES", "nc_liabilities"),
    ("NON CURRENT LIABILITY", "nc_liabilities"),
    ("Current Liabitities", "c_liabilities"),               # OCR misspelling
    ("SHARE CAPITAL AND RESERVES", "equity"),
    ("EQUITY AND LIABILITIES", "equity"),
    ("CURRENT ASSETS", "c_assets"),
    ("CONTINGENCIES AND COMMITMENTS", "end"),
    ("Trade and other payables", None),
])
def test_section_header(label, section):
    assert S.section_header(S.squash(label)) == section


# ------------------------------------------------------------------ statements from inline text
def _words(rows: list[tuple]) -> list[S.Word]:
    """rows of (label, note, current, prior) laid out like a PSX statement:
    labels from x=50, notes right-aligned at 375, figures at 445 and 512."""
    out, y = [], 100.0
    for label, note, *vals in rows:
        x = 50.0
        for tok in label.split():
            out.append(S.Word(x, x + 5 * len(tok), y, y + 8, tok))
            x += 5 * len(tok) + 3
        if note:
            out.append(S.Word(375 - 5 * len(note), 375, y, y + 8, note))
        for right, v in zip((445.0, 512.0), vals):
            if v:
                out.append(S.Word(right - 5 * len(v), right, y, y + 8, v))
        y += 12
    return out


BS_ROWS = [
    ("2020 2019", "", "", ""),
    ("EQUITY AND LIABILITIES", "", "", ""),
    ("SHARE CAPITAL AND RESERVES", "", "", ""),
    ("Authorized share capital", "", "1,000,000,000", "1,000,000,000"),
    ("Issued, subscribed and paid up share capital", "4", "948,399,800", "948,399,800"),
    ("Accumulated loss", "", "(5,201,976,599)", "(4,587,511,104)"),
    ("Revaluation surplus on property, plant and equipment", "6", "2,451,434,093", "2,500,224,322"),
    ("", "", "(1,802,142,706)", "(1,138,887,000)"),
    ("Long term loan from holding company", "7", "2,532,527,126", "1,773,441,126"),
    ("", "", "730,384,420", "634,554,126"),
    ("NON CURRENT LIABILITIES", "", "", ""),
    ("Long term financing from banking companies", "8", "2,022,113,765", "1,892,941,955"),
    ("Deferred liabilities", "12", "989,710,316", "918,820,123"),
    ("", "", "3,011,824,081", "2,811,762,078"),
    ("CURRENT LIABILITIES", "", "", ""),
    ("Trade and other payables", "14", "699,141,931", "905,966,038"),
    ("Short term borrowings", "15", "100,000,000", "-"),
    ("", "", "799,141,931", "905,966,038"),
    ("CONTINGENCIES AND COMMITMENTS", "20", "", ""),
    ("", "", "4,541,350,432", "4,352,282,242"),
    ("ASSETS", "", "", ""),
    ("NON CURRENT ASSETS", "", "", ""),
    ("Operating fixed assets", "21", "4,000,000,000", "3,800,000,000"),
    ("", "", "4,000,000,000", "3,800,000,000"),
    ("CURRENT ASSETS", "", "", ""),
    ("Trade deposits, short term prepayments and", "", "", ""),
    ("current account balances with statutory authorities", "28", "534,350,432", "503,371,091"),
    ("Cash and bank balances", "29", "7,000,000", "48,911,151"),
    ("", "", "541,350,432", "552,282,242"),
    ("", "", "4,541,350,432", "4,352,282,242"),
]


def test_parse_balance_unlabelled_subtotals():
    lines = S._join_wrapped(S.build_lines(_words(BS_ROWS), 1, "text"))
    assert S.current_column(lines) == 0
    got = {k: h.value for k, h in S.parse_balance(lines).items()}
    # the sponsor loan printed after the equity subtotal stays outside equity
    assert got["equity"] == -1_802_142_706
    assert got["share_cap"] == 948_399_800
    assert got["nc_liabilities"] == 3_011_824_081
    assert got["c_liabilities"] == 799_141_931
    assert got["liabilities"] == 3_011_824_081 + 799_141_931      # derived
    assert got["nc_assets"] == 4_000_000_000
    assert got["c_assets"] == 541_350_432
    assert got["assets"] == 4_541_350_432
    assert got["cabb"] == 7_000_000
    assert got["st_borr"] == 100_000_000
    assert got["lt_debt"] == 2_022_113_765


def test_wrapped_label_joined():
    lines = S._join_wrapped(S.build_lines(_words(BS_ROWS), 1, "text"))
    assert any(ln.label.startswith("Trade deposits, short term prepayments and current account")
               for ln in lines)


def test_parse_balance_last_subtotal_wins():
    """Share capital net of a discount is subtotalled first; the section total
    is the later subtotal that includes it."""
    rows = [
        ("2023 2022", "", "", ""),
        ("SHARE CAPITAL AND RESERVES", "", "", ""),
        ("Share capital", "13", "378,738,210", "378,738,210"),
        ("Discount on issue of right shares", "14", "(180,795,726)", "(180,795,726)"),
        ("", "", "197,942,484", "197,942,484"),
        ("Unappropriated profit", "", "488,074,372", "351,650,169"),
        ("", "", "686,016,856", "549,592,653"),
        ("NON CURRENT LIABILITIES", "", "", ""),
    ]
    got = S.parse_balance(S._join_wrapped(S.build_lines(_words(rows), 1, "text")))
    assert got["equity"].value == 686_016_856


def test_current_column_prior_year_first():
    rows = [("2019 2020", "", "", ""), ("Share capital", "", "100,000", "120,000"),
            ("Reserves", "", "50,000", "60,000"), ("Total equity", "", "150,000", "180,000")]
    lines = S.build_lines(_words(rows), 1, "text")
    assert S.current_column(lines) == 1


def test_parse_income():
    rows = [
        ("2020 2019", "", "", ""),
        ("Sales", "", "1,000,000", "900,000"),
        ("Less: sales tax", "", "(150,000)", "(130,000)"),
        ("Net sales", "", "850,000", "770,000"),
        ("Cost of sales", "30", "(600,000)", "(500,000)"),
        ("Gross profit", "", "250,000", "270,000"),
        ("(Loss)/profit before taxation", "", "(100,000)", "120,000"),
        ("Taxation", "36", "(30,000)", "(35,000)"),
        ("(Loss)/profit after taxation", "", "(130,000)", "85,000"),
        ("Total comprehensive (loss)/income for the year", "", "(130,000)", "85,000"),
        ("Earnings per share", "", "", ""),
        ("Basic and diluted", "37", "(7.33)", "6.59"),
    ]
    got = {k: h.value for k, h in S.parse_income(S.build_lines(_words(rows), 1, "text")).items()}
    assert got == {"sales": 850_000, "pbt": -100_000, "pat": -130_000, "eps": -7.33}


def test_parse_income_net_sales_as_bare_subtotal():
    rows = [("2022 2021", "", "", ""), ("Sales", "", "8,300,430", "8,494,799"),
            ("Less: Sales tax", "", "1,210,522", "1,235,543"), ("", "", "7,089,908", "7,259,256"),
            ("Cost of sales", "", "7,155,205", "6,762,523"), ("Gross (loss) / profit", "", "(65,297)", "496,733")]
    got = S.parse_income(S.build_lines(_words(rows), 1, "text"))
    assert got["sales"].value == 7_089_908


def test_parse_income_segment_profit_and_eps():
    """Refinery-style P&L: profit 'from refinery operations', then the year's total; EPS per segment."""
    rows = [("2022 2021", "", "", ""), ("Net sales", "", "261,983,815", "127,730,407"),
            ("Profit/(loss) after taxation from refinery operations", "", "9,096,713", "(2,265,351)"),
            ("Income from non-refinery operations less applicable charges", "", "834,000", "120,295"),
            ("Profit/(loss) for the year", "", "9,930,713", "(2,145,056)"),
            ("Earnings/(Loss) per share - basic and diluted", "", "", ""),
            ("Refinery operations", "", "85.32", "(21.25)"), ("Non-refinery operations", "", "7.82", "1.13"),
            ("", "", "93.14", "(20.12)")]
    got = {k: h.value for k, h in S.parse_income(S.build_lines(_words(rows), 1, "text")).items()}
    assert got["pat"] == 9_930_713 and got["eps"] == pytest.approx(93.14)


def test_split_panels_spread():
    left = [S.Word(50 + i, 100 + i, 10 * i, 10 * i + 8, "left") for i in range(10)]
    right = [S.Word(700 + i, 760 + i, 10 * i, 10 * i + 8, "right") for i in range(10)]
    panels = S.split_panels(left + right, 1224, 846)
    assert len(panels) == 2 and panels[0] == left and panels[1] == right
    assert len(S.split_panels(left, 612, 792)) == 1                     # portrait: untouched


def test_title_line_required():
    assert S.has_title("ITTEFAQ IRON INDUSTRIES LIMITED\nCOND'ENSEDINTERIM STATEMENT OF FINANCIAL POSITION", "bs")
    assert S.has_title("Chief Financial Officer\nUNCONSOLIDATED STATEMENT OF \nFINANCIAL POSITION", "bs")
    assert S.has_title("CONDENSED INTERIM PROFIT AND LOSS ACCOUNT (UN-AUDITED)", "pl")
    # a notes page mentions the statements mid-sentence: not a title
    assert not S.has_title("19.1 Staff retirement benefits\nMovement in the net liability recognized in "
                           "balance sheet", "bs")
    assert not S.has_title("Impact on statement of profit or loss", "pl")
    assert S.title_strength("STATEMENT OF COMPREHENSIVE INCOME", "pl") == 1


def test_garbled_share():
    clean = [S.Word(0, 1, 0, 1, t) for t in ["1,234", "(5,678)", "948,399,800"] * 5]
    bad = [S.Word(0, 1, 0, 1, t) for t in ["218,,232488,,098495", "28,348,9453", "1,234"] * 5]
    assert S.garbled_share(clean) == 0.0
    assert S.garbled_share(bad) > 0.5


def test_side_by_side_balance_sheet_split():
    """Liabilities left, assets right, on one portrait page."""
    words, y = [], 100.0
    for left, right in [("Share capital", "Property, plant and equipment"), ("Accumulated loss", "Long term deposits"),
                        ("Trade payables", "Stock in trade"), ("Accrued mark up", "Trade debts"),
                        ("Short term borrowings", "Loans and advances"), ("Unclaimed dividend", "Other receivables"),
                        ("Taxation payable", "Cash and bank balances")]:
        for x, label, cols in ((40, left, (200, 260)), (290, right, (470, 530))):
            for k, tok in enumerate(label.split()):
                words.append(S.Word(x + 30 * k, x + 30 * k + 25, y, y + 8, tok))
            for c in cols:
                words.append(S.Word(c - 40, c, y, y + 8, "1,234,567"))
        y += 12
    sides = S.split_side_by_side(words, "text")
    assert len(sides) == 2
    assert all(w.x1 <= 270 for w in sides[0]) and all(w.x0 >= 280 for w in sides[1])


def test_score_prefers_unconsolidated():
    body = "\n".join(["Share capital 1,000 1,000", "Trade and other payables 2,000 2,000",
                      "Current liabilities", "Current assets", "Total assets 9,999 9,999",
                      "Cash and bank balances 1,000 1,000"] + [f"Item {i} 1,{i:03d} 2,{i:03d}" for i in range(20)])
    plain = "Statement of Financial Position\nAs at June 30, 2024\n" + body
    cons = "Consolidated Statement of Financial Position\nAs at June 30, 2024\n" + body
    glance = "Six years at a glance\nBalance sheet\n" + body
    assert S.score_page(plain, "bs") > S.MIN_SCORE
    assert S.score_page(cons, "bs") < S.score_page(plain, "bs") - 5
    assert S.score_page(glance, "bs") < S.MIN_SCORE
    assert math.isfinite(S.score_page("", "pl"))
