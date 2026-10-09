"""Single LLM calls with structured output (NOT agents).

Every non-agent model call in the pipeline goes through `structured_call`:
  * Responses API + Pydantic schema -> the model must return valid JSON.
  * Cache key = (stage, model, prompt_version, input). Re-running the pipeline
    on unchanged input costs nothing; bumping prompt_version invalidates.
  * Token usage is recorded per stage in a ledger, so cost per proposal can be
    reported (phase 8).

Document text is always passed as *data* inside a delimited block, never mixed
into the instructions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from grant_screening import azure_clients as az
from grant_screening.cache import cached_json, digest, trial_salt

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
T = TypeVar("T", bound=BaseModel)

# gpt-5.4-mini, Global Standard, USD per 1M tokens (Azure Retail Prices API, 2026-10-01)
PRICE_PER_M = {"input": 0.75, "cached_input": 0.075, "output": 4.50}


@dataclass
class Usage:
    stage: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False  # served from local cache: no tokens were billed

    @property
    def usd(self) -> float:
        if self.cached:
            return 0.0
        return (self.input_tokens * PRICE_PER_M["input"] + self.output_tokens * PRICE_PER_M["output"]) / 1e6


@dataclass
class Ledger:
    entries: list[Usage] = field(default_factory=list)

    def add(self, usage: Usage) -> None:
        self.entries.append(usage)

    def summary(self) -> dict:
        billed = [u for u in self.entries if not u.cached]
        return {
            "llm_calls": len(self.entries),
            "billed_calls": len(billed),
            "input_tokens": sum(u.input_tokens for u in self.entries),
            "output_tokens": sum(u.output_tokens for u in self.entries),
            "usd_billed": round(sum(u.usd for u in billed), 5),
            "usd_if_uncached": round(sum((u.input_tokens * PRICE_PER_M["input"] + u.output_tokens * PRICE_PER_M["output"]) / 1e6
                                         for u in self.entries), 5),
            "by_stage": {s: sum(1 for u in self.entries if u.stage == s) for s in dict.fromkeys(u.stage for u in self.entries)},
        }


def load_prompt(name: str) -> tuple[str, str]:
    """Return (version, text). The first line of a prompt file is 'version: <v>'."""
    raw = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    first, _, body = raw.partition("\n")
    if not first.startswith("version:"):
        raise ValueError(f"prompt {name} must start with 'version: <v>'")
    return first.split(":", 1)[1].strip(), body.strip()


def data_block(title: str, content: str) -> str:
    return f"<<<{title}\n{content}\n{title}>>>"


def structured_call(stage: str, prompt_name: str, document: str, schema: type[T],
                    ledger: Ledger | None = None, effort: str = "low", sample: int = 0) -> T:
    """sample > 0 requests an additional independent sample (own cache entry)."""
    version, instructions = load_prompt(prompt_name)
    model = az.chat_deployment()
    key = digest("llm", trial_salt(), f"s{sample}" if sample else "", stage, model, prompt_name, version, effort, schema.__name__,
                 json.dumps(schema.model_json_schema(), sort_keys=True), document)
    fresh = {"hit": True}

    def call() -> dict:
        fresh["hit"] = False
        resp = az.chat_client().responses.parse(
            model=model,
            instructions=instructions,
            input=document,
            text_format=schema,
            reasoning={"effort": effort},
        )
        return {"parsed": resp.output_parsed.model_dump(mode="json"),
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens}

    stored = cached_json("llm", key, call)
    if ledger is not None:
        ledger.add(Usage(stage, stored["input_tokens"], stored["output_tokens"], cached=fresh["hit"]))
    return schema.model_validate(stored["parsed"])
