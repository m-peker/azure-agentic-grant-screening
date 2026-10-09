"""Open the screening UI locally: start screenings, watch them live, decide.

Usage: python scripts/ui.py            # http://127.0.0.1:8000 opens in the browser
       python scripts/ui.py --port 8080 --no-browser

Requires: az login and .env (python scripts/write_env.py).
"""
from __future__ import annotations

import os
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8000
    os.environ["GRANT_UI_LOCAL"] = "1"
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "webapp"))

    import uvicorn

    from grant_screening import telemetry

    telemetry.setup("grant-screening-ui")
    url = f"http://127.0.0.1:{port}"
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"Ön Uygunluk arayüzü: {url}   (durdurmak için Ctrl+C)")
    uvicorn.run("app:app", host="127.0.0.1", port=port, log_level="warning")
