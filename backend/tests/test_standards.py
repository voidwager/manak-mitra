"""find_standard: product description -> the published BIS list rows.

The table fixture below uses the exact shapes of the two BIS pages the seed
corpus captures - the Scheme-I list (with a divider row, "IS number") and
the CRS list (no divider, "Indian Standard number( IS No.)") - because a
parser tested only against a tidy table is how the CRS list silently
contributed zero rows the first time.
"""

import pytest

from app.tools.builtin.standards import StandardRow, parse_tables, rank

SCHEME_I = """\
| Sr | Product category | IS number | Product | QCO | Scheme |
|---|---|---|---|---|---|
| 1 | Cement | IS 269 | Ordinary Portland Cement | Q001 Cement (Quality Control)Order, 2003 | Scheme-I (ISI Mark) |
| 2 | Kitchen appliances | IS 2347:2017 | Domestic Pressure Cooker | Q010 Pressure Cooker (Quality Control) Order, 2020 | Scheme-I (ISI Mark) |
| 3 | Kitchen appliances | IS 7466 :1994 | Rubber Gaskets for Pressure Cookers | Q010 Pressure Cooker (Quality Control) Order, 2020 | Scheme-I (ISI Mark) |
| 4 | Automotive | IS 4151: 2015 | Helmet for riders of Two Wheeler Motor Vehicles | Q020 Helmet (QC) Order | Scheme-I (ISI Mark) |
| 5 | Water | IS 14543 | Packaged Drinking Water | Q030 Food (QC) Order | Scheme-I (ISI Mark) |
| 6 | Household Electrical goods | IS 694 | PVC insulated cables for working voltages up to 1100V | Q002 Electrical Wires | Scheme-I (ISI Mark) |
| 7 | Steel | IS 6911 | Stainless steel plate, sheet and strip | Q040 Stainless Steel (QC) Order | Scheme-I (ISI Mark) |
| 8 | Steel | IS 1239 (Part 1) | Steel tubes, tubulars and other wrought steel fittings | Q041 Steel (QC) Order | Scheme-I (ISI Mark) |
| 9 | Steel | IS 2062 | Hot rolled medium and high tensile structural steel | Q041 Steel (QC) Order | Scheme-I (ISI Mark) |
"""

CRS = """\
# Following products are covered under Compulsory Registration Scheme:
| Sl. No. | Product | Indian Standard number( IS No.) | Date of Implementation of QCO |
| 1 | LAPTOP/NOTEBOOK/TABLET | IS 13252(Part 1):2010 | 03 July 2013 |
| 2 | POWER BANKS FOR USE IN PORTABLE APPLICATIONS | IS 13252(Part 1):2010 | 01 Jan 2017 |
| 3 | SELF-BALLASTED LED LAMPS FOR GENERAL LIGHTING SERVICES | IS 16102(Part 1):2012 | 03 July 2013 |
"""

PROSE_WITH_TABLE = """\
Fees are payable as below.

| Item | Fee |
|---|---|
| Application | Rs 1000 |
"""


@pytest.fixture(scope="module")
def rows():
    out = []
    for name, text in (("scheme-i.md", SCHEME_I), ("crs.md", CRS)):
        out += [StandardRow(name, name, c, r, n) for c, r, n in parse_tables(text)]
    return out


def _top(rows, query, limit=3):
    return [row.is_number for _, row in rank(rows, query, limit)]


def test_both_table_shapes_are_parsed(rows):
    assert sum(r.document_id == "scheme-i.md" for r in rows) == 9
    assert sum(r.document_id == "crs.md" for r in rows) == 3
    assert all(r.is_number.startswith("IS") for r in rows)


def test_a_table_without_an_is_column_is_not_a_product_list():
    assert parse_tables(PROSE_WITH_TABLE) == []


def test_the_product_word_decides_not_the_material(rows):
    """'steel' is on hundreds of real rows; 'cooker' is on two."""
    assert _top(rows, "stainless steel pressure cooker")[0] == "IS 2347:2017"


def test_an_is_number_is_an_exact_lookup(rows):
    assert _top(rows, "what does IS 4151 cover?") == ["IS 4151: 2015"]


def test_electronics_come_from_the_crs_list(rows):
    assert _top(rows, "USB power bank") == ["IS 13252(Part 1):2010"]


def test_how_people_say_it_maps_to_how_bis_lists_it(rows):
    assert _top(rows, "LED bulb") == ["IS 16102(Part 1):2012"]


def test_sharing_a_word_is_not_a_match(rows):
    """'PVC pipes for drinking water' must not return Packaged Drinking Water
    or PVC cables - each shares a word and neither is the product. Returning
    them would put a wrong IS number in front of a manufacturer, cited."""
    assert _top(rows, "PVC pipes for drinking water") == []


def test_what_a_product_is_for_does_not_disqualify_it(rows):
    """No row says "for house construction"; cement rows still apply."""
    assert _top(rows, "cement for house construction") == ["IS 269"]


def test_the_head_noun_is_the_product():
    from app.tools.builtin.standards import head_token

    assert head_token("stainless steel pressure cookers") == "cooker"
    assert head_token("PVC pipes for drinking water") == "pipe"
    assert head_token("which standard applies to pressure cookers?") == "cooker"
    assert head_token("helmet for two wheeler riders") == "helmet"


def test_a_match_says_which_of_the_users_words_it_does_not_cover(rows):
    from app.tools.builtin.standards import unmatched_words

    cooker = next(r for r in rows if r.is_number == "IS 2347:2017")
    assert unmatched_words(cooker, "stainless steel pressure cooker") == [
        "stainless",
        "steel",
    ]
    assert unmatched_words(cooker, "pressure cooker") == []


def test_an_unlisted_product_returns_nothing(rows):
    assert _top(rows, "wooden dining chair") == []


def test_an_empty_description_returns_nothing(rows):
    assert _top(rows, "   ") == []
    assert _top(rows, "which standard applies") == []
