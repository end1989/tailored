from __future__ import annotations

import threading
import webbrowser

import uvicorn
from dotenv import load_dotenv

load_dotenv()

from backend.app.config import get_settings  # noqa: E402
from backend.app.main import create_app  # noqa: E402


def main() -> None:
    settings = get_settings()
    app = create_app(settings=settings)
    url = f"http://{settings.host}:{settings.port}"
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
