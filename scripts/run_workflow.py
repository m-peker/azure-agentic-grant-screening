"""Run the Agent Framework workflow from the terminal (the UI uses the same module).

  python scripts/run_workflow.py start MGA-2026-0147 [MGA-...]
  python scripts/run_workflow.py review MGA-2026-0147 APPROVE "Ayşe Uzman" RETURN_FOR_REVISION "not"
  python scripts/run_workflow.py sync            # apply decisions submitted in the cloud UI
  python scripts/run_workflow.py process-inbox   # screen proposals uploaded in the cloud UI

Easier: python scripts/ui.py  (start, watch and decide in the browser)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grant_screening import telemetry  # noqa: E402
from grant_screening.workflow import runner  # noqa: E402
from grant_screening.workflow.graph import OfficerDecision  # noqa: E402


async def _print(e: dict) -> None:
    if e["event"] == "completed":
        print(f"  ✓ {e['stage']:3} {e['label']}")
    elif e["event"] == "paused":
        print(f"  ⏸ Program Uzmanı kararı bekleniyor (sistem önerisi: {e['decision']})")
    elif e["event"] == "finished":
        print(f"  ■ bitti: {e['decision']}")
    elif e["event"] == "error":
        print(f"  ✗ hata: {e['detail']}")


async def main(cmd: str, args: list[str]) -> None:
    telemetry.setup()
    if cmd == "start" and args:
        for app in args:
            print(app)
            await runner.start(app, _print)
    elif cmd == "review" and len(args) >= 4:
        out = await runner.resume(args[0], OfficerDecision(officer=args[2], action=args[1], final_decision=args[3],
                                                           note=args[4] if len(args) > 4 else ""))
        print(f"RESUMED  : {args[0]} officer={out['officer']['officer']} final={out['officer']['final_decision']}")
    elif cmd == "sync":
        print("\n".join(await runner.sync()))
    else:
        print(__doc__)
    telemetry.flush()


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["help"]
    asyncio.run(main(cmd, rest))
