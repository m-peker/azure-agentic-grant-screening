import pytest

from conftest import APP_IDS, GOLDEN, load_layout
from grant_screening.intake.layout import (
    known_section_titles,
    parse_amount,
    parse_budget_table,
    parse_sections,
)

BUDGET_IDS = [a for a in APP_IDS if "budget" in GOLDEN[a]]


@pytest.mark.parametrize("app_id", BUDGET_IDS)
def test_budget_matches_golden(app_id):
    table = parse_budget_table(load_layout(app_id))
    gold = GOLDEN[app_id]["budget"]
    assert table.by_category() == gold["rows"]
    assert table.rows_sum == gold["rows_sum"]


def test_table_split_across_pages_is_merged():
    # MGA-2026-0213: Layout returns 2 fragments (page 1: header + 1 row, page 2: rest)
    table = parse_budget_table(load_layout("MGA-2026-0213"))
    assert table.fragments == 2
    assert len(table.rows) == 6


def test_wrong_total_row_is_exposed_not_trusted():
    # MGA-2026-0388: the document's own "Toplam" row is wrong
    table = parse_budget_table(load_layout("MGA-2026-0388"))
    assert table.total_row_amount == 1_380_000
    assert table.rows_sum == 1_480_000


@pytest.mark.parametrize("app_id", ["MGA-2026-0147", "MGA-2026-0213", "MGA-2026-0388"])
def test_all_required_sections_found(app_id):
    titles = {s.title for s in parse_sections(load_layout(app_id))}
    assert set(known_section_titles()) <= titles


def test_heading_without_layout_role_is_still_found():
    # Layout never tags "Özet" as sectionHeading; name matching must catch it.
    layout = load_layout("MGA-2026-0147")
    roles = {p["content"]: p.get("role") for p in layout["paragraphs"]}
    assert roles.get("Özet") is None
    assert "Özet" in {s.title for s in parse_sections(layout)}


def test_missing_sections_detectable():
    titles = {s.title for s in parse_sections(load_layout("MGA-2026-0402"))}
    missing = set(known_section_titles()) - titles
    assert {"Amaç ve Hedefler", "Etik Değerlendirme", "Risk Yönetimi"} <= missing


def test_orphan_header_cells_not_in_section_text():
    sections = parse_sections(load_layout("MGA-2026-0147"))
    budget = next(s for s in sections if s.title == "Bütçe ve Gerekçe")
    assert not {"Kalem", "Tutar (TL)", "Gerekçe"} & {p.text for p in budget.paragraphs}


@pytest.mark.parametrize("app_id", APP_IDS)
def test_invisible_text_never_reaches_layout_output(app_id):
    assert "yapay zekâ sistemi" not in load_layout(app_id)["content"]


@pytest.mark.parametrize(
    "text, expected",
    [("1.449.000", 1_449_000), ("1.449.000 TL", 1_449_000), ("**930.000**", 930_000),
     ("1.449.000,00", 1_449_000), ("420000", 420_000), ("", None), ("belirlenecek", None)],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected
