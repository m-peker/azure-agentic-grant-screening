"""Stage C: rule gate. Pure code: dates, numbers, presence. No model involved.

Every result carries the call section it is based on and the template that
will explain it to the applicant, with placeholder values computed here.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
RULEBOOK_DIR = ROOT / "scenario" / "rulebook"

COMPLIANT = "COMPLIANT"
COMPLIANT_EXT = "COMPLIANT_WITH_EXTENSION"
COMPLIANT_EXC = "COMPLIANT_WITH_EXCEPTION"
VIOLATION = "VIOLATION"
UNRESOLVED = "UNRESOLVED"        # data missing or unverified -> human
NOT_EVALUATED = "NOT_EVALUATED"  # skipped after a gate failure
PASSING = {COMPLIANT, COMPLIANT_EXT, COMPLIANT_EXC}
SEMANTIC_PENDING = "semantic-pending"


@dataclass
class RuleResult:
    rule_id: str
    status: str
    severity: str
    source: str
    template: str | None = None
    value: object = None
    limit: object = None
    detail: str = ""
    placeholders: dict = field(default_factory=dict)
    exception: dict | None = None
    gate: bool = False
    title: str = ""      # human-readable rule name (from the rulebook)
    summary: str = ""    # one human-readable line for the officer UI (see describe())

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Rulebook selection (by call and date, like every other document)
# ---------------------------------------------------------------------------
def load_rulebook(call_id: str, on: date, version: int | None = None) -> dict:
    """Highest rulebook version for the call that is in force on `on` (the screening date).

    `version` pins an explicit version (used to compare v2 and v3 in evaluation).
    """
    candidates = []
    for path in RULEBOOK_DIR.glob("*.yaml"):
        rb = yaml.safe_load(path.read_text(encoding="utf-8"))
        rb["_file"] = path.name
        if rb["call_id"] != call_id:
            continue
        if version is not None:
            if rb["version"] == version:
                return rb
            continue
        start, end = rb["effective_from"], rb.get("effective_to")
        if start <= on and (end is None or on <= end):
            candidates.append(rb)
    if not candidates:
        raise LookupError(f"no rulebook for {call_id} on {on} (version={version})")
    return max(candidates, key=lambda rb: rb["version"])


def source_label(rule: dict) -> str:
    s = rule["source"]
    return f"{s['doc_id']} v{s['version']} §{s['section']}"


# ---------------------------------------------------------------------------
# Formatting helpers (Turkish)
# ---------------------------------------------------------------------------
def tl(n: int | None) -> str:
    return "?" if n is None else f"{n:,}".replace(",", ".")


def pct(x: float) -> str:
    return f"{x:.0f}" if abs(x - round(x)) < 1e-9 else f"{x:.2f}".replace(".", ",")


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------
def _eligibility(rule: dict, s: dict, deadline: date) -> RuleResult:
    base = RuleResult(rule["id"], UNRESOLVED, rule["severity"], source_label(rule), rule.get("template"),
                      gate=rule.get("gate", False))
    phd = s["phd_date"]
    if phd["status"] != "ok":
        base.detail = f"doktora tarihi okunamadı ({phd['status']})"
        return base
    phd_date = date.fromisoformat(phd["value"])

    ext_months = 0
    for lv in s["leaves"]:
        if lv["status"] != "ok":
            base.detail = "izin beyanı doğrulanamadı"
            return base
        if lv["leave_type"] == "parental":
            ext_months += next(e["add_months"] for e in rule["extensions"] if e["leave_type"] == "parental")
        elif lv["months"] is not None:
            ext_months += lv["months"]
        else:
            base.detail = "sağlık izni süresi okunamadı"
            return base
    if ext_months and (s.get("leave_documents") or {}).get("status") != "ok":
        base.detail = "izin beyan edilmiş ama belgelerin eklendiği gösterilmemiş"
        return base

    base_limit = add_months(phd_date, rule["base_limit_months"])
    limit = add_months(phd_date, rule["base_limit_months"] + ext_months)
    base.value = phd_date.isoformat()
    base.limit = limit.isoformat()
    base.placeholders = {"phd_date": phd_date.strftime("%d.%m.%Y"), "limit_date": limit.strftime("%d.%m.%Y")}
    if deadline <= base_limit:
        base.status = COMPLIANT
    elif deadline <= limit:
        base.status = COMPLIANT_EXT
        base.detail = f"{ext_months} ay izin uzatmasıyla"
    else:
        base.status = VIOLATION
        base.detail = f"son başvuru {deadline.isoformat()} > üst sınır {limit.isoformat()}"
    return base


def _compare(value, op: str, limit) -> bool:
    return {"<=": value <= limit, ">=": value >= limit, "==": value == limit}[op]


def _numeric(rule: dict, value, field_name: str) -> RuleResult:
    r = RuleResult(rule["id"], UNRESOLVED, rule["severity"], source_label(rule), rule.get("template"))
    if value is None:
        r.detail = f"{field_name} okunamadı"
        return r
    r.value = value
    r.placeholders = {"value": value}
    failed = [c for c in rule["checks"] if not _compare(value, c["operator"], c["limit"])]
    r.limit = " ve ".join(f"{c['operator']} {c['limit']}" for c in rule["checks"])
    r.status = VIOLATION if failed else COMPLIANT
    return r


def _budget_rules(rule: dict, budget: dict | None, declared: int | None) -> RuleResult:
    r = RuleResult(rule["id"], UNRESOLVED, rule["severity"], source_label(rule), rule.get("template"))
    if not budget:
        r.detail = "bütçe tablosu bulunamadı (Kalem ve Tutar sütunlu tablo yok)"
        return r
    doubt = budget_parse_doubt(budget)
    if doubt:
        # Asymmetric trust: a table we could not read is OUR problem. It goes to a human
        # and never becomes a sentence like "your budget totals 0 TL" in the applicant's letter.
        r.detail = doubt
        return r
    cats = budget["by_category"]
    total = budget["rows_sum"]
    rid = rule["id"]
    if rid == "R-BUD-01":
        r.value, r.limit = total, rule["limit"]
        r.placeholders = {"value": tl(total)}
        r.status = COMPLIANT if total <= rule["limit"] else VIOLATION
    elif rid == "R-BUD-02":
        indirect = cats.get("dolayli", 0)
        direct = total - indirect
        value = round(indirect / direct * 100, 2) if direct else 0.0
        r.value, r.limit = value, rule["limit"]
        r.placeholders = {"value": pct(value), "max_amount": tl(int(direct * rule["limit"] / 100))}
        r.status = COMPLIANT if value <= rule["limit"] else VIOLATION
    elif rid == "R-BUD-03":
        value = round(cats.get("ekipman", 0) / total * 100, 2) if total else 0.0
        r.value, r.limit = value, rule["limit"]
        r.placeholders = {"value": pct(value)}
        r.status = COMPLIANT if value <= rule["limit"] else VIOLATION
    elif rid == "R-BUD-04":
        if declared is None:
            r.detail = "beyan edilen toplam okunamadı"
            return r
        r.value, r.limit = total, declared
        r.placeholders = {"rows_sum": tl(total), "declared": tl(declared)}
        r.status = COMPLIANT if total == declared else VIOLATION
        if r.status == VIOLATION:
            r.detail = f"tablo satırları {tl(total)} TL, beyan {tl(declared)} TL"
    return r


def budget_parse_doubt(budget: dict) -> str:
    """Signs that the table was misread rather than wrongly filled in. Empty string = trust it."""
    unreadable = [r["label"] for r in budget["rows"] if r["amount"] is None]
    if unreadable:
        return "bütçe tablosunda tutarı okunamayan satır: " + ", ".join(unreadable)
    if budget["rows_sum"] <= 0:
        return "bütçe tablosu okundu ama tutarlar toplanamadı (toplam 0)"
    # A "Toplam" row that disagrees with the rows is NOT a doubt: it is a real applicant error
    # that R-BUD-04 must report (MGA-2026-0388). Only unreadable or empty amounts are ours.
    return ""


# If more than this share of the required sections is "missing", the headings were most likely
# not recognised (format, numbering, unread pages): a stage problem for a human, not a deficiency.
SECTION_DOUBT_SHARE = 0.5


def _sections(rule: dict, titles: list[str]) -> RuleResult:
    required = rule["required_sections"]
    missing = [t for t in required if t not in titles]
    r = RuleResult(rule["id"], VIOLATION if missing else COMPLIANT, rule["severity"], source_label(rule),
                   rule.get("template"), value=len(required) - len(missing), limit=len(required))
    r.placeholders = {"missing": ", ".join(missing)}
    r.detail = f"eksik: {', '.join(missing)}" if missing else ""
    if len(missing) > len(required) * SECTION_DOUBT_SHARE:
        r.status = UNRESOLVED
        r.detail = (f"{len(missing)}/{len(required)} zorunlu bölüm bulunamadı; başlıklar büyük olasılıkla "
                    "tanınamadı, uzman kontrol etmeli")
    return r


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def evaluate(intake: dict, structured: dict, rulebook: dict) -> tuple[list[RuleResult], bool]:
    """Return (results, gate_failed). After a gate failure the rest is NOT_EVALUATED."""
    deadline = rulebook["application_deadline"]
    titles = [s["title"] for s in intake["sections"]]
    declared = structured["declared_total"]["value"] if structured["declared_total"]["status"] == "ok" else None
    duration = structured["duration_months"]["value"] if structured["duration_months"]["status"] == "ok" else None

    results: list[RuleResult] = []
    gate_failed = False
    for rule in rulebook["rules"]:
        if gate_failed:
            results.append(RuleResult(rule["id"], NOT_EVALUATED, rule["severity"], source_label(rule),
                                      detail="uygunluk kapısından sonra değerlendirilmedi"))
            continue
        rid = rule["id"]
        # check_type first: "R-BUD-05" is semantic even though its id starts with "R-BUD-"
        if rule["check_type"] == "semantic":
            # evaluated by rules/semantic.py (LLM with verified quotes); placeholder until then
            r = RuleResult(rid, UNRESOLVED, rule["severity"], source_label(rule), rule.get("template"),
                           detail=SEMANTIC_PENDING)
        elif rid == "R-ELG-01":
            r = _eligibility(rule, structured, deadline)
        elif rid == "R-DUR-01":
            r = _numeric(rule, duration, "proje süresi")
        elif rid.startswith("R-BUD-"):
            r = _budget_rules(rule, intake.get("budget"), declared)
        elif rid == "R-DOC-01":
            r = _numeric(rule, intake["page_count"], "sayfa sayısı")
        elif rid == "R-DOC-02":
            r = _sections(rule, titles)
        else:
            r = RuleResult(rid, UNRESOLVED, rule["severity"], source_label(rule), detail="bilinmeyen kural türü")
        if rid == "R-ELG-01" and r.status == VIOLATION and not structured["leaves"] \
                and declared_leave_mentioned(intake):
            # Asymmetric trust: a model OMISSION may send a proposal to a human,
            # never reject it. The form mentions leave but nothing was extracted.
            r.status = UNRESOLVED
            r.detail = "beyan formunda izin ifadesi var ama çıkarılamadı; uzatma insan tarafından kontrol edilmeli"
        results.append(r)
        if rule.get("gate") and r.status == VIOLATION:
            gate_failed = True
    return results, gate_failed


# "izin" loses its vowel when suffixed ("ebeveyn izni"), so match both stems
LEAVE_RE = re.compile(r"(ebeveyn|doğum|analık|babalık|sağlık|hastalık)\w*\s+izi?n", re.IGNORECASE)
NEGATION_RE = re.compile(r"kullanmam|kullanılmam|almam|yoktur|bulunmamakta|söz konusu değil", re.IGNORECASE)


def declared_leave_mentioned(intake: dict) -> bool:
    """Code-only check: does the application declare a leave anywhere?

    Declaration form: any 'izin' line whose value is not 'Yok'. Free text (forms without a
    declaration section, real upload 2026-10-02): a leave phrase that is not negated.
    False positives only send a proposal to a human, so the check is deliberately broad."""
    for s in intake["sections"]:
        for p in s["paragraphs"]:
            text = p["text"]
            if s["title"] == "Beyan Formu":
                label, sep, value = text.partition(":")
                if sep and re.search(r"izi?n", label.casefold()) and not value.strip().casefold().startswith("yok"):
                    return True
            elif LEAVE_RE.search(text) and not NEGATION_RE.search(text):
                return True
    return False


# ---------------------------------------------------------------------------
# Human-readable summaries (officer UI). Data-driven: rulebook title + display_unit.
# ---------------------------------------------------------------------------
def _d(iso) -> str:
    try:
        return date.fromisoformat(str(iso)).strftime("%d.%m.%Y")
    except ValueError:
        return str(iso)


def describe(r: RuleResult, rule: dict) -> None:
    r.title = rule.get("title", r.rule_id)
    unit = rule.get("display_unit")
    if r.status == NOT_EVALUATED:
        r.summary = "Yürütücü uygunluğu sağlanmadığı için değerlendirilmedi"
        return
    if r.status == UNRESOLVED:
        r.summary = r.detail or "Otomatik olarak karar verilemedi; uzman kontrolü gerekli"
        return
    v, lim = r.value, r.limit
    if unit == "date":
        r.summary = f"Doktora {_d(v)} · son tarih {_d(lim)}"
        if r.status == COMPLIANT_EXT:
            r.summary += f" ({r.detail})"
    elif unit == "months":
        r.summary = f"{v} ay · izin verilen 12–24 ay"
    elif unit == "try" and r.rule_id == "R-BUD-04":
        r.summary = f"Tablo toplamı {tl(v)} TL · beyan {tl(lim)} TL"
    elif unit == "try":
        r.summary = f"{tl(v)} TL · üst sınır {tl(lim)} TL"
    elif unit == "percent":
        r.summary = f"%{pct(v)} · üst sınır %{pct(lim)}"
        exc = r.exception or {}
        if r.status == COMPLIANT_EXC:
            r.summary += f" (geçerli ön onay {exc.get('preapproval_id')} ile %{rule['exception']['max_with_exception']})"
        elif exc.get("status") == "INVALID":
            r.summary += f" · ön onay geçersiz: {exc.get('reason')}"
    elif unit == "pages":
        r.summary = f"{v} sayfa · üst sınır 15"
    elif unit == "sections":
        r.summary = f"{v}/{lim} bölüm mevcut" + (f" · {r.detail}" if r.detail else "")
    elif unit == "check":
        r.summary = r.detail if r.detail else ("Karşılandı" if r.status in PASSING else "Karşılanmadı")
    else:
        r.summary = r.detail


def describe_all(results: list[RuleResult], rulebook: dict) -> list[RuleResult]:
    rules = {x["id"]: x for x in rulebook["rules"]}
    for r in results:
        describe(r, rules[r.rule_id])
    return results
