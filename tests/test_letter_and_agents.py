import asyncio
from datetime import date
from types import SimpleNamespace

from grant_screening.agents.tools import BUDGET_NOTICE, ToolRun, build_tools
from grant_screening.llm_stages import letter
from test_extract import load


# --- template lock ---------------------------------------------------------
def test_lock_accepts_tokens_without_digits():
    ok, _ = letter.lock_ok("Sayın Başvuru Sahibi,\n- {{T1}}\n- {{T2}}\nProgram Ofisi", 2)
    assert ok


def test_lock_rejects_invented_numbers():
    ok, why = letter.lock_ok("Dolaylı gider %12 olmalı. {{T1}}", 1)
    assert not ok and "rakam" in why


def test_lock_rejects_missing_or_duplicate_tokens():
    assert not letter.lock_ok("{{T1}} {{T1}}", 2)[0]
    assert not letter.lock_ok("{{T2}}", 2)[0]


def test_render_uses_code_values():
    s = letter.render("TPL-INDIRECT", {"value": "15", "max_amount": "126.000"})
    assert "%15" in s and "126.000 TL" in s


def test_code_only_letter_for_early_exit():
    out = letter.write_letter("MGA-2026-0402", ["cümle"], use_llm=False)
    assert out["mode"] == "code" and "MGA-2026-0402" in out["text"]


# --- agent tools and budget -----------------------------------------------
def test_tools_are_read_only_and_identity_free():
    tools = build_tools(load("intake", "MGA-2026-0147"), date(2026, 9, 30), lambda q, d: [])
    assert set(tools) == {"read_section", "find_term", "list_attachments", "get_budget_line",
                          "search_call_docs", "get_announcement", "get_registry_entry"}
    entry = tools["get_registry_entry"].func("ON-2025-031")
    assert "applicant_orcid" not in entry and "MGA-2025" in entry


def test_tool_schemas_are_strict():
    tools = build_tools(load("intake", "MGA-2026-0147"), date(2026, 9, 30), lambda q, d: [])
    for t in tools.values():
        schema = t.parameters()
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


def test_budget_middleware_stops_tools():
    run = ToolRun(budget=2)
    mw = run.middleware()
    calls = []

    async def call_next():
        calls.append(1)

    async def invoke():
        ctx = SimpleNamespace(function=SimpleNamespace(name="find_term"), arguments={"term": "x"}, result="ok")
        await mw(ctx, call_next)
        return ctx.result

    results = [asyncio.run(invoke()) for _ in range(3)]
    assert len(calls) == 2                 # third call never reached the tool
    assert results[2] == BUDGET_NOTICE
    assert [c["result"] for c in run.calls][-1] == "budget_exhausted"
