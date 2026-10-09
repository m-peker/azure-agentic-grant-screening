"""(Re)build the AI Search index from scenario/call/ and run a filter demo.

Usage: python scripts/build_search_index.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grant_screening.search.index import build_index, search_call_docs  # noqa: E402

DEADLINE = date(2026, 9, 30)
QUERY = "dolaylı gider üst sınırı yüzde kaç"

if __name__ == "__main__":
    print(f"uploaded {build_index()} chunks")
    for label, on in (("validity filter ON ", DEADLINE), ("validity filter OFF", None)):
        print(f"\n{label}: {QUERY}")
        for h in search_call_docs(QUERY, on):
            print(f"  {h['id']:24} {h['content'][:70]}")
