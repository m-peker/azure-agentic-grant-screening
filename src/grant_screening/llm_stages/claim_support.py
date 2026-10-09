"""Stage F2: claim support — does the evidence actually support the conclusion?

F1 already proved that every quote exists. F2 asks a different question: given
only those quotes, does the agent's conclusion follow? This is an LLM-as-judge
check on LLM-produced findings only (code results need no judge).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from grant_screening.llm import Ledger, data_block, structured_call


class Support(BaseModel):
    supported: Literal["SUPPORTED", "NOT_SUPPORTED"]
    reason: str = Field(description="One sentence in Turkish")


def check_support(conclusion: str, evidence: list[dict], ledger: Ledger | None = None) -> dict:
    ev = "\n".join(f"- ({e['source']}) {e['quote']}" for e in evidence)
    doc = data_block("SONUC", conclusion) + "\n\n" + data_block("KANITLAR", ev)
    return structured_call("F2-claim-support", "claim_support", doc, Support, ledger=ledger).model_dump()
