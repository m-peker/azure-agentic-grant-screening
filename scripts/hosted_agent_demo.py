"""Publish the Investigator to Foundry Agent Service and run it on one flag.

Usage: python scripts/hosted_agent_demo.py
Afterwards the agent and its versions are visible in the Foundry portal (Agents).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grant_screening.agents.hosted import AGENT_NAME, investigate_hosted, publish  # noqa: E402
from grant_screening.cache import CACHE_ROOT  # noqa: E402
from grant_screening.search.index import search_call_docs  # noqa: E402

DEADLINE = date(2026, 9, 30)
TASK = ("İşaretlenen risk — çağrı maddesi 4.6.\n"
        "Şüpheler: 180.000 TL hizmet alımında sağlayıcı belirtilmemiş ve teklif eklenmemiş olabilir.\n"
        "Başvurudan alıntılar: Hizmet alımı | 180.000 TL | µ-FTIR polimer tayini analizleri\n"
        "Bu riskin gerçek olup olmadığını araştır ve karar ver.")

if __name__ == "__main__":
    intake = json.loads((CACHE_ROOT / "intake" / "MGA-2026-0147.json").read_text(encoding="utf-8"))
    version = publish(intake, DEADLINE, search_call_docs)
    print(f"published {AGENT_NAME} version {version}")
    out = investigate_hosted(version, TASK, intake, DEADLINE, search_call_docs)
    r = out["result"]
    print(f"verdict : {r['verdict']}  (evidence problems: {r['evidence_problems'] or 'none'})")
    print(f"tools   : {[c['tool'] for c in out['tool_calls']]}")
    print(f"tokens  : {out['input_tokens']} in / {out['output_tokens']} out")
    print(f"why     : {r['rationale']}")
