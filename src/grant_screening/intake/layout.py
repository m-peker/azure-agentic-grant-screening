"""Stage A1: Document Intelligence Layout -> sections and the budget table.

Lessons baked into this module (measured on the scenario PDFs, 2026-10-01):

1. Layout reads the page like a human does. White 1pt text is NOT in its output.
   Feeding only Layout text to the LLM therefore keeps invisible injections away
   from the model. Detection still happens on the PDF text layer (hidden_text.py).
2. Tables that cross a page break come back as separate fragments, and an orphan
   header row may come back as plain paragraphs. Fragments are merged here.
3. Not every heading gets role=sectionHeading ("Özet" never did). Headings are
   also recognised by matching known section names from the rulebook.
4. Budget amounts are parsed from table cells by code. The LLM never does
   arithmetic and never reads the numbers (architecture decision #1).

Lessons from the first real uploads (2026-10-02, a 3-page proposal):

5. The F0 (free) tier analyses ONLY THE FIRST 2 PAGES of a document, silently.
   Page 3 (end of the budget table, ethics section) simply did not exist for the
   pipeline. Longer PDFs are now analysed in 2-page parts and merged, and the
   page coverage is checked (a gap is a stage problem, never an applicant error).
6. Real documents number their headings ("3. İş Paketleri ve Zaman Çizelgesi").
   Headings are normalised (number prefix, Turkish case) and mapped to the
   rulebook's canonical names through `section_aliases`.
7. Columns are found by their header ("Tutar"), not by position.
"""
from __future__ import annotations

import io
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml
from pypdf import PdfReader, PdfWriter

from grant_screening import azure_clients as az
from grant_screening.cache import cached_json, digest

ROOT = Path(__file__).resolve().parents[3]
RULEBOOK_DIR = ROOT / "scenario" / "rulebook"
LAYOUT_MODEL = "prebuilt-layout"
# Document Intelligence F0 analyses only the first 2 pages per request. S0 has no such limit;
# set DOCUMENT_INTELLIGENCE_PAGES_PER_CALL=0 there to always send the whole document at once.
PAGES_PER_CALL = int(os.environ.get("DOCUMENT_INTELLIGENCE_PAGES_PER_CALL", "2"))

# Sections that exist in the form but are not "required sections" of rule R-DOC-02.
EXTRA_SECTIONS = ["Yürütücü Bilgileri", "Beyan Formu"]

# Budget labels are matched by prefix after normalisation: "sarf malzemesi", "seyahat giderleri"...
BUDGET_CATEGORIES = {
    "personel": "personel",
    "ekipman": "ekipman",
    "makine": "ekipman",
    "sarf": "sarf",
    "seyahat": "seyahat",
    "hizmet alım": "hizmet",
    "dolaylı gider": "dolayli",
    "genel gider": "dolayli",
}
TOTAL_LABELS = {"toplam", "genel toplam", "toplam bütçe"}
LABEL_HEADERS = ("kalem", "bütçe kalemi", "gider kalemi")
AMOUNT_HEADERS = ("tutar", "miktar (tl)", "bütçe (tl)")
NOTE_HEADERS = ("gerekçe", "açıklama")
# Header cells of a table whose header row was orphaned on the previous page
# come back as plain paragraphs; drop them from section text.
ORPHAN_HEADER_CELLS = {"kalem", "bütçe kalemi", "tutar (tl)", "tutar", "gerekçe", "açıklama"}
APPLICATION_NO_RE = re.compile(r"Başvuru\s+(?:No|Numarası)\W{0,12}(MGA-\d{4}-\d{4})", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Service call (cached by PDF content hash)
# ---------------------------------------------------------------------------
def _analyze_bytes(data: bytes, key: str) -> dict:
    def call() -> dict:
        from azure.ai.documentintelligence import DocumentIntelligenceClient

        client = DocumentIntelligenceClient(os.environ["DOCUMENT_INTELLIGENCE_ENDPOINT"], az.credential())
        return client.begin_analyze_document(LAYOUT_MODEL, body=data).result().as_dict()

    return cached_json("layout", key, call)


def pdf_page_count(data: bytes) -> int:
    return len(PdfReader(io.BytesIO(data)).pages)


def _page_range(data: bytes, start: int, end: int) -> bytes:
    reader, writer = PdfReader(io.BytesIO(data)), PdfWriter()
    for i in range(start, end):
        writer.add_page(reader.pages[i])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _shift(node, page_offset: int, char_offset: int, in_spans: bool = False):
    """Move one part's result to its place in the whole document (page numbers + content offsets)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "pageNumber" and isinstance(v, int):
                node[k] = v + page_offset
            elif k == "offset" and in_spans and isinstance(v, int):
                node[k] = v + char_offset
            else:
                _shift(v, page_offset, char_offset, in_spans or k == "spans")
    elif isinstance(node, list):
        for item in node:
            _shift(item, page_offset, char_offset, in_spans)
    return node


def merge_layouts(parts: list[tuple[int, dict]]) -> dict:
    """[(first_page_index, result), ...] -> one result, as if the whole PDF had been analysed at once."""
    merged = json.loads(json.dumps(parts[0][1]))
    for first_page, part in parts[1:]:
        char_offset = len(merged["content"]) + 1
        part = _shift(json.loads(json.dumps(part)), first_page, char_offset)
        merged["content"] = merged["content"] + "\n" + part["content"]
        for k, v in part.items():
            if isinstance(v, list):
                merged[k] = merged.get(k, []) + v
    return merged


def analyze_layout(pdf_path: str | Path) -> dict:
    """Layout for the WHOLE document. F0 stops after 2 pages, so the rest is sent in parts."""
    data = Path(pdf_path).read_bytes()
    first = _analyze_bytes(data, digest(LAYOUT_MODEL, data))
    total, done = pdf_page_count(data), len(first.get("pages", []))
    if done >= total or PAGES_PER_CALL <= 0:
        return first
    step = max(1, min(PAGES_PER_CALL, done or PAGES_PER_CALL))
    parts = [(0, first)]
    for start in range(done, total, step):
        end = min(start + step, total)
        part = _analyze_bytes(_page_range(data, start, end), digest(LAYOUT_MODEL, data, f"pages:{start}-{end}"))
        parts.append((start, part))
    return merge_layouts(parts)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------
@dataclass
class Paragraph:
    text: str
    page: int
    offset: int  # character offset in layout["content"]; used later for quote checks


@dataclass
class Section:
    title: str
    paragraphs: list[Paragraph] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.paragraphs)


@dataclass
class BudgetRow:
    label: str
    category: str | None  # None -> unknown label, to be classified in stage B
    amount: int | None
    justification: str
    page: int


@dataclass
class BudgetTable:
    rows: list[BudgetRow]
    total_row_amount: int | None  # what the document's own "Toplam" row claims
    fragments: int                # how many Layout tables were merged

    @property
    def rows_sum(self) -> int:
        return sum(r.amount or 0 for r in self.rows)

    def by_category(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.rows:
            if r.category and r.amount is not None:
                out[r.category] = out.get(r.category, 0) + r.amount
        return out

    def to_dict(self) -> dict:
        return asdict(self) | {"rows_sum": self.rows_sum, "by_category": self.by_category()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def tr_lower(text: str) -> str:
    """Turkish lower case: İ -> i, I -> ı (str.casefold turns 'I' into 'i' and 'İ' into 'i' + dot)."""
    return text.replace("İ", "i").replace("I", "ı").lower()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", tr_lower(text.replace("*", ""))).strip()


HEADING_NUMBER_RE = re.compile(r"^\d+(\.\d+)*[.)]?\s*")


def norm_heading(text: str) -> str:
    """'3. İş Paketleri ve Zaman Çizelgesi:' -> 'iş paketleri ve zaman çizelgesi'"""
    return _norm(HEADING_NUMBER_RE.sub("", text.strip())).rstrip(":").strip()


def _section_rules() -> list[dict]:
    out = []
    for path in sorted(RULEBOOK_DIR.glob("*.yaml")):
        rules = yaml.safe_load(path.read_text(encoding="utf-8"))["rules"]
        out += [r for r in rules if r["id"] == "R-DOC-02"]
    return out


def known_section_titles() -> list[str]:
    titles: list[str] = []
    for rule in _section_rules():
        titles += [t for t in rule["required_sections"] if t not in titles]
    return [*titles, *EXTRA_SECTIONS]


def heading_map() -> dict[str, str]:
    """normalised heading or alias -> canonical section name (union of all rulebook versions)."""
    out = {norm_heading(t): t for t in known_section_titles()}
    for rule in _section_rules():
        for canonical, aliases in (rule.get("section_aliases") or {}).items():
            for a in aliases:
                out.setdefault(norm_heading(a), canonical)
    return out


def budget_category(label: str) -> str | None:
    key = _norm(label)
    return next((c for prefix, c in BUDGET_CATEGORIES.items() if key.startswith(prefix)), None)


def application_number(layout: dict) -> str | None:
    """The applicant's own number as printed on the form (letters must quote it, not our internal id)."""
    m = APPLICATION_NO_RE.search(layout.get("content", ""))
    return m.group(1) if m else None


def document_title(layout: dict) -> str | None:
    return next((p["content"].strip() for p in layout.get("paragraphs", []) if p.get("role") == "title"), None)


def parse_amount(text: str) -> int | None:
    """'1.449.000' / '1.449.000 TL' / '1.449.000,00' -> 1449000. Turkish separators."""
    cleaned = text.replace("TL", "").replace("₺", "").replace("*", "").strip()
    cleaned = re.sub(r",\d{1,2}$", "", cleaned)          # drop kuruş
    cleaned = cleaned.replace(".", "").replace(" ", "")
    return int(cleaned) if cleaned.isdigit() else None


def _table_spans(layout: dict) -> list[tuple[int, int]]:
    return [(s["offset"], s["offset"] + s["length"]) for t in layout.get("tables", []) for s in t["spans"]]


def _in_spans(offset: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= offset < b for a, b in spans)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
def _is_budget_table(table: dict) -> bool:
    grid = [cells for _, cells in _grid(table)]
    return any(_columns(c) for c in grid) or sum(1 for c in grid if c and budget_category(c[0])) >= 2


def _table_rows_as_paragraphs(table: dict) -> list[Paragraph]:
    """A form table ("Proje süresi | 24 ay") becomes "Proje süresi: 24 ay" lines in the section text.
    Lesson (real upload): skipping every table dropped the applicant's info table, so the model
    never saw the PhD date, duration or declared total that the form puts there."""
    out = []
    by_row: dict[int, list[dict]] = {}
    for c in table["cells"]:
        by_row.setdefault(c["rowIndex"], []).append(c)
    for i in sorted(by_row):
        cells = sorted(by_row[i], key=lambda c: c["columnIndex"])
        values = [c["content"].strip() for c in cells if c["content"].strip()]
        if not values:
            continue
        text = f"{values[0]}: {' | '.join(values[1:])}" if len(values) > 1 else values[0]
        first = cells[0]
        offset = first["spans"][0]["offset"] if first.get("spans") else table["spans"][0]["offset"]
        out.append(Paragraph(text, first["boundingRegions"][0]["pageNumber"], offset))
    return out


def parse_sections(layout: dict) -> list[Section]:
    titles = heading_map()
    tables = [(t, [(s["offset"], s["offset"] + s["length"]) for s in t["spans"]]) for t in layout.get("tables", [])]
    emitted: set[int] = set()
    sections: list[Section] = [Section(title="_preamble")]
    for p in layout["paragraphs"]:
        offset = p["spans"][0]["offset"]
        hit = next((i for i, (_, spans) in enumerate(tables) if _in_spans(offset, spans)), None)
        if hit is not None:
            # budget table cells are handled by parse_budget_table; other tables become text once
            table = tables[hit][0]
            if hit not in emitted and not _is_budget_table(table):
                sections[-1].paragraphs.extend(_table_rows_as_paragraphs(table))
            emitted.add(hit)
            continue
        text = p["content"].strip()
        if _norm(text) in ORPHAN_HEADER_CELLS:
            continue
        key = norm_heading(text)
        is_heading = p.get("role") == "sectionHeading" or key in titles
        if is_heading:
            sections.append(Section(title=titles.get(key, HEADING_NUMBER_RE.sub("", text))))
        else:
            sections[-1].paragraphs.append(Paragraph(text, p["boundingRegions"][0]["pageNumber"], offset))
    return [s for s in sections if s.title != "_preamble" or s.paragraphs]


# ---------------------------------------------------------------------------
# Budget table
# ---------------------------------------------------------------------------
def _grid(table: dict) -> list[tuple[int, list[str]]]:
    rows: dict[int, list[str]] = {}
    pages: dict[int, int] = {}
    for c in table["cells"]:
        r = rows.setdefault(c["rowIndex"], [""] * table["columnCount"])
        r[c["columnIndex"]] = c["content"].strip()
        pages.setdefault(c["rowIndex"], c["boundingRegions"][0]["pageNumber"])
    return [(pages[i], rows[i]) for i in sorted(rows)]


def _merge_fragments(tables: list[dict]) -> list[list[dict]]:
    """Group Layout tables that are one logical table split across pages."""
    groups: list[list[dict]] = []
    for t in tables:
        first_page = min(r["pageNumber"] for r in t["boundingRegions"])
        if groups:
            prev = groups[-1][-1]
            prev_last = max(r["pageNumber"] for r in prev["boundingRegions"])
            if prev["columnCount"] == t["columnCount"] and first_page == prev_last + 1:
                groups[-1].append(t)
                continue
        groups.append([t])
    return groups


def _columns(cells: list[str]) -> dict[str, int | None] | None:
    """Header row -> {label, amount, note} column indexes; None if this is not a budget header."""
    norm = [_norm(c) for c in cells]

    def find(names: tuple[str, ...]) -> int | None:
        return next((i for i, c in enumerate(norm) if any(c.startswith(n) for n in names)), None)

    label, amount = find(LABEL_HEADERS), find(AMOUNT_HEADERS)
    if label is None or amount is None:
        return None
    return {"label": label, "amount": amount, "note": find(NOTE_HEADERS)}


def _guess_columns(grid: list[list[str]]) -> dict:
    """No header (orphaned on the previous page): the amount column is the one whose cells parse as amounts."""
    width = max(len(r) for r in grid)
    hits = [sum(1 for r in grid if i < len(r) and parse_amount(r[i]) is not None) for i in range(width)]
    amount = max(range(1, width), key=lambda i: hits[i]) if width > 1 else 0
    note = next((i for i in range(1, width) if i != amount), None)
    return {"label": 0, "amount": amount, "note": note}


def parse_budget_table(layout: dict) -> BudgetTable | None:
    """The budget table is the one with a 'Kalem' + 'Tutar' header and a 'Toplam' row (or, failing
    that, the most known budget categories). Columns come from the header, never from position."""
    best, best_score = None, 0
    for group in _merge_fragments(layout.get("tables", [])):
        rows: list[BudgetRow] = []
        total: int | None = None
        cols: dict | None = None
        has_header = has_total = False
        for fragment in group:
            grid = _grid(fragment)
            for page, cells in grid:
                header = _columns(cells)
                if header:  # also a header repeated on the next page
                    cols, has_header = header, True
                    continue
                c = cols or _guess_columns([g for _, g in grid])
                label = cells[c["label"]]
                amount = parse_amount(cells[c["amount"]]) if c["amount"] < len(cells) else None
                if _norm(label) in TOTAL_LABELS:
                    total, has_total = amount, True
                    continue
                if not label and amount is None:
                    continue
                note = c["note"]
                rows.append(BudgetRow(
                    label=label,
                    category=budget_category(label),
                    amount=amount,
                    justification=cells[note] if note is not None and note < len(cells) else "",
                    page=page,
                ))
        known = sum(1 for r in rows if r.category)
        if known < 2:
            continue
        score = known + (10 if has_header else 0) + (5 if has_total else 0)
        if score > best_score:
            best, best_score = BudgetTable(rows=rows, total_row_amount=total, fragments=len(group)), score
    return best
