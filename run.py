"""Tailored launcher: loads .env, starts the server, opens the browser.

Usage: python run.py
"""
from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

# No sys.path manipulation: `python run.py` from the project root already puts
# the root on sys.path, and the backend package is only ever imported as
# `backend.app.*` (matching Task 1's run.py, conftest.py, and every test).
PROJECT_ROOT = Path(__file__).resolve().parent


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    from backend.app.config import get_settings
    from backend.app.main import create_app

    settings = get_settings()
    url = f"http://{settings.host}:{settings.port}"
    print("=" * 62)
    print("  Tailored — AI Resume & Cover Letter Builder")
    print(f"  Open {url} in your browser (opening automatically...)")
    print("  Press Ctrl+C to stop.")
    print("=" * 62)
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
