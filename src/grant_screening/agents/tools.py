"""Read-only tools for the two agents, plus a per-run budget.

Design rules (see docs/architecture.md, "Agent'lar"):
  * Every tool is READ-ONLY. An agent can be wrong; it can never change state.
  * Tools see the pseudonymised application only. No tool returns identity data.
  * Every call is recorded (name, arguments, short result) for the audit trail.
  * A budget caps tool calls. When it is exhausted, tools answer with a notice
    instead of data, and the agent must conclude with what it has.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Callable

from pydantic import Field

from agent_framework import FunctionInvocationContext, function_middleware, tool

from grant_screening import corpus
from grant_screening.rules.citations import budget_line_text
from grant_screening.rules.exceptions import load_registry

BUDGET_NOTICE = "BUTCE_DOLDU: Araç bütçen bitti. Yeni araç çağırma; elindeki kanıtla kararını ver."


@dataclass
class ToolRun:
    budget: int
    calls: list[dict] = field(default_factory=list)

    @property
    def exhausted(self) -> bool:
        return len(self.calls) >= self.budget

    def middleware(self):
        run = self

        @function_middleware
        async def budget_and_audit(context: FunctionInvocationContext, call_next):
            name = context.function.name
            args = dict(context.arguments) if hasattr(context, "arguments") and context.arguments else {}
            if run.exhausted:
                context.result = BUDGET_NOTICE
                run.calls.append({"tool": name, "args": _jsonable(args), "result": "budget_exhausted"})
                return
            await call_next()
            # full text is kept (up to 4k): a tool result can be cited as evidence ("tool:<name>")
            run.calls.append({"tool": name, "args": _jsonable(args), "result": _result_text(context.result)[:4000]})

        return budget_and_audit


def _result_text(result) -> str:
    """Tool results arrive as a list of Content objects; keep their text for the audit trail."""
    if isinstance(result, (list, tuple)):
        return " ".join(_result_text(r) for r in result)
    return getattr(result, "text", None) or str(result)


def _jsonable(d) -> dict:
    try:
        return json.loads(json.dumps(d, default=str))
    except Exception:  # noqa: BLE001
        return {"repr": repr(d)}


SearchFn = Callable[[str, date], list[dict]]


def build_tools(intake: dict, deadline: date, search: SearchFn) -> dict[str, object]:
    """Return tool functions bound to one application. Keys are tool names."""
    sections = {s["title"]: "\n".join(p["text"] for p in s["paragraphs"]) for s in intake["sections"]}
    budget_rows = (intake.get("budget") or {}).get("rows", [])

    @tool
    def read_section(title: Annotated[str, Field(description="Başvuru bölümünün başlığı, ör. 'Etik Değerlendirme'")]) -> str:
        """Başvurunun bir bölümünün tam metnini döndürür."""
        if title in sections:
            return sections[title] or "(bölüm boş)"
        return "Bölüm bulunamadı. Mevcut bölümler: " + ", ".join(t for t in sections if t != "_preamble")

    @tool
    def find_term(term: Annotated[str, Field(description="Aranacak kelime veya ifade")]) -> str:
        """Başvuruda bir ifadenin geçtiği paragrafları (en fazla 5) bölüm adıyla döndürür."""
        t = term.casefold()
        hits = [f"[{s['title']}] {p['text']}" for s in intake["sections"] for p in s["paragraphs"]
                if t in p["text"].casefold()]
        return "\n".join(hits[:5]) if hits else f"'{term}' başvuruda geçmiyor."

    @tool
    def list_attachments() -> str:
        """Başvuruya eklendiği beyan edilen belgeleri döndürür (Beyan Formu 'Ekler' satırı ve metindeki Ek atıfları)."""
        lines = [p["text"] for s in intake["sections"] for p in s["paragraphs"]
                 if p["text"].startswith("Ekler") or "Ek-" in p["text"]]
        lines += [f"Bütçe satırı: {r['label']} — {r['justification']}" for r in budget_rows if "Ek-" in r["justification"]]
        return "\n".join(lines) if lines else "Başvuruda ek listesi bulunamadı."

    @tool
    def get_budget_line(category: Annotated[str, Field(description="Bütçe kalemi: personel, ekipman, sarf, seyahat, hizmet, dolayli")]) -> str:
        """Bir bütçe kaleminin tablodaki tutarını ve gerekçesini döndürür. Tutarlar tablodan kodla okunmuştur."""
        rows = [r for r in budget_rows if r["category"] == category.strip().casefold()]
        if not rows:
            return f"'{category}' kalemi bütçe tablosunda yok."
        # Same canonical text as everywhere else, so a quote of this line verifies (source='application').
        return "\n".join(budget_line_text(r) for r in rows)

    @tool
    def search_call_docs(query: Annotated[str, Field(description="Çağrı belgelerinde aranacak soru veya ifade")]) -> str:
        """Çağrı metni ve duyurularda hybrid arama yapar. Yalnızca son başvuru tarihinde yürürlükte olan metinleri döndürür."""
        hits = search(query, deadline)
        if not hits:
            return "Sonuç yok."
        return "\n".join(f"[{h['id']}] {h['content']}" for h in hits)

    @tool
    def get_announcement(name: Annotated[str, Field(description="Duyuru adı, ör. 'Duyuru-3'")]) -> str:
        """Bir duyurunun tam metnini döndürür (son başvuru tarihinde yürürlükteyse)."""
        c = corpus.find_announcement(name, deadline)
        return f"[{c.id}] {c.content}" if c else f"'{name}' bulunamadı veya yürürlükte değil."

    @tool
    def get_registry_entry(preapproval_id: Annotated[str, Field(description="Ön onay numarası, ör. 'ON-2026-012'")]) -> str:
        """Ön onay sicilinden bir kaydı döndürür. Kimlik bilgisi (ORCID) döndürülmez."""
        e = next((x for x in load_registry() if x["preapproval_id"] == preapproval_id.strip()), None)
        if e is None:
            return f"{preapproval_id} sicilde yok."
        safe = {k: v for k, v in e.items() if k != "applicant_orcid"}
        return json.dumps(safe, ensure_ascii=False)

    tools = (read_section, find_term, list_attachments, get_budget_line,
             search_call_docs, get_announcement, get_registry_entry)
    return {f.name: strict(f) for f in tools}


def strict(t):
    """Rebuild a tool with a strict JSON schema (additionalProperties: false, all fields required).

    Foundry Agent Service rejects non-strict function schemas for hosted prompt agents
    (400 invalid_function_parameters). Strict schemas are also safer locally: the model
    cannot invent extra arguments.
    """
    schema = dict(t.parameters())
    schema.pop("title", None)
    schema["additionalProperties"] = False
    schema["required"] = list(schema.get("properties", {}))
    schema.setdefault("properties", {})
    return tool(t.func, name=t.name, description=t.description, schema=schema)
