"""Regressions from the first real uploads (2026-10-02).

A 3-page proposal in a different layout produced a letter saying "your budget totals 0 TL"
and "7 required sections are missing". Causes: Document Intelligence F0 reads only 2 pages,
amounts were read by column position, numbered headings did not match, and parse failures
were reported to the applicant as deficiencies. MGA-2026-0519/0520 are fictional twins.
"""
import pytest

from conftest import PDF_DIR, load_layout
from grant_screening import screening as S
from grant_screening.intake import layout as L
from grant_screening.intake.pipeline import run_intake
from grant_screening.llm import Ledger
from grant_screening.rules import decision, engine
from test_rules import DEADLINE


# --- reading the whole document --------------------------------------------------------
def test_three_page_layout_is_complete_and_offsets_line_up():
    lay = load_layout("MGA-2026-0519")
    assert [p["pageNumber"] for p in lay["pages"]] == [1, 2, 3]
    for p in lay["paragraphs"]:
        span = p["spans"][0]
        assert lay["content"][span["offset"]:span["offset"] + span["length"]] == p["content"]


def test_parts_are_merged_with_shifted_pages_and_offsets():
    def part(text, page):
        return {"content": text, "pages": [{"pageNumber": page}],
                "paragraphs": [{"content": text, "spans": [{"offset": 0, "length": len(text)}],
                                "boundingRegions": [{"pageNumber": page}]}]}
    merged = L.merge_layouts([(0, part("ilk", 1)), (2, part("son", 1))])
    last = merged["paragraphs"][-1]
    assert last["boundingRegions"][0]["pageNumber"] == 3
    assert merged["content"][last["spans"][0]["offset"]:][:3] == "son"


def test_long_pdf_is_sent_in_parts(monkeypatch, tmp_path):
    calls = []

    def fake(data, key):
        calls.append(key)
        n = L.pdf_page_count(data)
        return {"content": "x", "pages": [{"pageNumber": i + 1} for i in range(min(n, 2))], "paragraphs": []}
    monkeypatch.setattr(L, "_analyze_bytes", fake)
    lay = L.analyze_layout(PDF_DIR / "MGA-2026-0519.pdf")   # 3 pages; F0 returns 2
    assert len(calls) == 2 and len(lay["pages"]) == 3


def test_unread_pages_are_a_stage_problem(offline, monkeypatch):
    two_pages = load_layout("MGA-2026-0519")
    two_pages = {**two_pages, "pages": two_pages["pages"][:2]}
    monkeypatch.setattr(L, "analyze_layout", lambda pdf: two_pages)
    result, _ = run_intake(PDF_DIR / "MGA-2026-0519.pdf", shield=offline, save=False)
    assert result.problems == ["belgenin yalnızca 2/3 sayfası okunabildi"]


# --- headings ----------------------------------------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("3. İş Paketleri ve Zaman Çizelgesi", "iş paketleri ve zaman çizelgesi"),
    ("1.2) Amaç ve Hedefler:", "amaç ve hedefler"),
    ("RİSK YÖNETİMİ", "risk yönetimi"),
    ("IŞIK", "ışık"),          # Turkish dotless I
])
def test_norm_heading(text, expected):
    assert L.norm_heading(text) == expected


def test_numbered_and_alias_headings_map_to_required_sections():
    titles = {s.title for s in L.parse_sections(load_layout("MGA-2026-0519"))}
    assert {"İş Paketleri ve Takvim", "Bütçe ve Gerekçe", "Etik Değerlendirme", "Amaç ve Hedefler"} <= titles
    assert set(L.known_section_titles()) - titles == {"Veri Yönetim Planı", "Yürütücü Bilgileri", "Beyan Formu"}


def test_info_table_reaches_section_text():
    texts = [p.text for s in L.parse_sections(load_layout("MGA-2026-0519")) for p in s.paragraphs]
    assert "Proje süresi: 24 ay" in texts and "Doktora derecesi alış tarihi: 03.09.2017" in texts


def test_application_number_from_the_form():
    assert L.application_number(load_layout("MGA-2026-0519")) == "MGA-2026-0519"


# --- budget table ------------------------------------------------------------------------
def test_amount_column_found_by_header_across_pages():
    table = L.parse_budget_table(load_layout("MGA-2026-0519"))   # Kalem | Açıklama | Tutar, pages 2-3
    assert table.fragments == 2
    assert table.rows_sum == 1_320_000 == table.total_row_amount
    assert table.by_category()["sarf"] == 120_000                # "Sarf malzemesi"
    assert table.rows[0].justification.startswith("1 doktora")


def test_amount_column_guessed_without_header():
    grid = [["Personel", "Açıklama metni", "430.000"], ["Ekipman", "sensör", "420.000"]]
    assert L._guess_columns(grid) == {"label": 0, "amount": 2, "note": 1}


# --- asymmetric trust: our parse failure is never the applicant's deficiency ------------
@pytest.fixture(scope="module")
def rulebook():
    return engine.load_rulebook("MGA-2026", DEADLINE)


def _rule(rulebook, rid):
    return next(r for r in rulebook["rules"] if r["id"] == rid)


def test_zero_budget_is_unresolved_not_violation(rulebook):
    budget = {"rows": [{"label": "Personel", "amount": 0}], "rows_sum": 0, "by_category": {}}
    r = engine._budget_rules(_rule(rulebook, "R-BUD-04"), budget, 1_320_000)
    assert r.status == engine.UNRESOLVED and "toplam 0" in r.detail


def test_unreadable_amount_is_unresolved(rulebook):
    budget = {"rows": [{"label": "Ekipman", "amount": None}], "rows_sum": 0, "by_category": {}}
    assert engine._budget_rules(_rule(rulebook, "R-BUD-01"), budget, None).status == engine.UNRESOLVED


def test_most_sections_missing_is_unresolved(rulebook):
    r = engine._sections(_rule(rulebook, "R-DOC-02"), ["Özet", "Yöntem"])
    assert r.status == engine.UNRESOLVED


def test_one_missing_section_is_still_a_deficiency(rulebook):
    rule = _rule(rulebook, "R-DOC-02")
    r = engine._sections(rule, [t for t in rule["required_sections"] if t != "Veri Yönetim Planı"])
    assert r.status == engine.VIOLATION


def test_unresolved_goes_to_officer_without_letter_sentence():
    results = [{"rule_id": "R-BUD-04", "status": engine.UNRESOLVED, "severity": "HIGH",
                "template": "TPL-BUDGET-SUM", "detail": "toplam 0"}]
    d = decision.decide(integrity_flag=False, gate_failed=False, rule_results=results,
                        cautions=[], stage_problems=[])
    assert d.decision == decision.OFFICER_REVIEW and d.templates == []


# --- letter ------------------------------------------------------------------------------
def _case(decision_name, templates):
    return {"application_id": "MGA-2026-5001", "gate_failed": True, "ledger": Ledger(), "trace": [],
            "intake": {"document_number": "MGA-2026-0519"},
            "rule_results": [{"template": "TPL-SECTIONS", "placeholders": {"missing": "Veri Yönetim Planı"}}],
            "decision": {"decision": decision_name, "templates": templates}}


def test_letter_quotes_the_number_on_the_form():
    case = S.stage_letter(_case(decision.OFFICER_REVIEW, ["TPL-SECTIONS"]))
    assert "MGA-2026-0519" in case["letter"]["text"] and "5001" not in case["letter"]["text"]


def test_no_letter_for_a_manipulated_document():
    case = S.stage_letter(_case(decision.INTEGRITY_REVIEW, ["TPL-SECTIONS"]))
    assert case["letter"]["mode"] == "withheld" and case["letter"]["text"] is None


# --- leave declared in free text (no declaration form) ----------------------------------
def _intake(*texts, title="Yürütücü Uygunluğu"):
    return {"sections": [{"title": title, "paragraphs": [{"text": t} for t in texts]}]}


def test_leave_in_free_text_blocks_a_rejection():
    assert engine.declared_leave_mentioned(_intake("Yürütücü, doktora sonrasında 2 adet ebeveyn izni kullanmıştır."))


def test_negated_leave_does_not_count():
    assert not engine.declared_leave_mentioned(_intake("Yürütücü doğum izni kullanmamıştır."))
    assert not engine.declared_leave_mentioned(_intake("Projede sağlık taraması yapılacaktır."))


def test_form_preamble_reaches_the_extractor():
    from grant_screening.structure import extract as ex
    text, _ = ex.number_paragraphs(_intake("Proje süresi: 24 ay", title="_preamble"))
    assert "## Form bilgileri" in text and "Proje süresi: 24 ay" in text
