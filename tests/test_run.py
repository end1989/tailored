from __future__ import annotations

import socket

import run
from backend.app import config as config_module


def test_port_in_use_true_while_bound_false_after_close():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    try:
        assert run.port_in_use("127.0.0.1", port) is True
    finally:
        listener.close()

    assert run.port_in_use("127.0.0.1", port) is False


def test_main_opens_browser_and_skips_server_when_already_running(monkeypatch):
    fake_settings = config_module.Settings(
        anthropic_api_key=None,
        data_dir="unused",
        fake_mode=True,
        host="127.0.0.1",
        port=8547,
    )
    monkeypatch.setattr(config_module, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(run, "port_in_use", lambda host, port: True)

    opened_urls = []
    monkeypatch.setattr(run.webbrowser, "open", lambda url: opened_urls.append(url))

    def _uvicorn_run_should_not_be_called(*args, **kwargs):
        raise AssertionError("uvicorn.run must not be called when the port is already in use")

    monkeypatch.setattr(run.uvicorn, "run", _uvicorn_run_should_not_be_called)

    result = run.main()

    assert result == 0
    assert opened_urls == ["http://127.0.0.1:8547"]
