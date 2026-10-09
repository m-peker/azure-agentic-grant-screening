"""Stage G1: deficiency letter with a template lock.

1. Code renders every approved template sentence with code-computed values.
2. The model writes only the frame (greeting, connecting sentences, closing)
   and refers to each sentence by a token {{T1}}, {{T2}}...
3. Code checks the frame: every token exactly once, no digits and no "%" of
   its own (so it cannot invent amounts, dates or rule numbers), then inserts
   the sentences verbatim.
If the frame fails the lock, a plain code-only letter is used instead.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from grant_screening.llm import Ledger, data_block, structured_call

ROOT = Path(__file__).resolve().parents[3]
TEMPLATES = ROOT / "scenario" / "templates" / "deficiency_templates.yaml"
TOKEN_RE = re.compile(r"\{\{T(\d+)\}\}")


def load_templates() -> dict[str, dict]:
    return {t["id"]: t for t in yaml.safe_load(TEMPLATES.read_text(encoding="utf-8"))["templates"]}


def render(template_id: str, placeholders: dict) -> str:
    return load_templates()[template_id]["text"].format(**placeholders)


class Frame(BaseModel):
    letter: str = Field(description="Turkish letter using {{T1}}..{{Tn}} tokens for the deficiency sentences")


def lock_ok(frame: str, n: int) -> tuple[bool, str]:
    tokens = [int(t) for t in TOKEN_RE.findall(frame)]
    if sorted(tokens) != list(range(1, n + 1)):
        return False, f"token kümesi hatalı: {tokens}"
    stripped = TOKEN_RE.sub("", frame)
    if re.search(r"[\d%]", stripped):
        return False, "çerçeve metninde rakam veya yüzde işareti var"
    return True, ""


def code_only_letter(application_id: str, sentences: list[str]) -> str:
    items = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences, start=1))
    return (f"Sayın Başvuru Sahibi,\n\n{application_id} numaralı başvurunuzun ön uygunluk incelemesinde "
            f"aşağıdaki hususlar tespit edilmiştir:\n\n{items}\n\nSaygılarımızla,\nProgram Ofisi")


def write_letter(application_id: str, sentences: list[str], use_llm: bool,
                 ledger: Ledger | None = None) -> dict:
    if not sentences:
        return {"text": None, "mode": "none", "lock": "n/a", "sentences": []}
    if not use_llm:
        return {"text": code_only_letter(application_id, sentences), "mode": "code", "lock": "n/a",
                "sentences": sentences}
    listing = "\n".join(f"{{{{T{i}}}}} = {s}" for i, s in enumerate(sentences, start=1))
    frame = structured_call("G1-letter", "letter", data_block("TESPITLER", listing), Frame, ledger=ledger).letter
    ok, why = lock_ok(frame, len(sentences))
    if not ok:
        return {"text": code_only_letter(application_id, sentences), "mode": "code-fallback", "lock": why,
                "sentences": sentences}
    text = TOKEN_RE.sub(lambda m: sentences[int(m.group(1)) - 1], frame)
    text = text.replace("{{BASVURU}}", application_id)
    return {"text": text, "mode": "llm-frame", "lock": "ok", "sentences": sentences}
