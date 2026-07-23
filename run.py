"""Tailored launcher: loads .env, starts the server, opens the browser.

Usage: python run.py
"""
from __future__ import annotations

import socket
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

# No sys.path manipulation: `python run.py` from the project root already puts
# the root on sys.path, and the backend package is only ever imported as
# `backend.app.*` (matching Task 1's run.py, conftest.py, and every test).
PROJECT_ROOT = Path(__file__).resolve().parent


def port_in_use(host: str, port: int) -> bool:
    """Return True if something is already listening on host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def main() -> int:
    # The banner below uses an em dash; cp1252 consoles (default on some
    # Windows setups) can't encode it and raise UnicodeEncodeError. Force
    # UTF-8 output when the stream supports reconfiguring.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv(PROJECT_ROOT / ".env")

    from backend.app.config import get_settings
    from backend.app.main import create_app

    settings = get_settings()
    url = f"http://{settings.host}:{settings.port}"

    if port_in_use(settings.host, settings.port):
        print("Tailored already seems to be running - opening your browser.")
        webbrowser.open(url)
        return 0

    print("=" * 62)
    print("  Tailored — AI Resume & Cover Letter Builder")
    print(f"  Open {url} in your browser (opening automatically...)")
    print("  Press Ctrl+C to stop.")
    print("=" * 62)
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    try:
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
    except KeyboardInterrupt:
        print("Stopped.")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
