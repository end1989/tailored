from __future__ import annotations

from backend.app.config import (
    DEFAULT_USER_SETTINGS,
    PROJECT_ROOT,
    Settings,
    load_user_settings,
    save_user_settings,
)

ENV_VARS = [
    "ANTHROPIC_API_KEY",
    "TAILORED_DATA_DIR",
    "TAILORED_FAKE",
    "TAILORED_HOST",
    "TAILORED_PORT",
]


def test_settings_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    monkeypatch.setenv("TAILORED_DATA_DIR", str(tmp_path / "custom"))
    monkeypatch.setenv("TAILORED_FAKE", "1")
    monkeypatch.setenv("TAILORED_HOST", "0.0.0.0")
    monkeypatch.setenv("TAILORED_PORT", "9000")
    s = Settings()
    assert s.anthropic_api_key == "sk-test-123"
    assert s.data_dir == tmp_path / "custom"
    assert s.fake_mode is True
    assert s.host == "0.0.0.0"
    assert s.port == 9000


def test_settings_defaults(monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.anthropic_api_key is None
    assert s.data_dir == PROJECT_ROOT / "data"
    assert s.fake_mode is False
    assert s.host == "127.0.0.1"
    assert s.port == 8547


def test_settings_kwargs_override_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TAILORED_FAKE", "0")
    monkeypatch.setenv("TAILORED_PORT", "9000")
    s = Settings(data_dir=tmp_path, fake_mode=True, port=1234)
    assert s.data_dir == tmp_path
    assert s.fake_mode is True
    assert s.port == 1234


def test_settings_explicit_none_api_key_beats_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-ignored")
    s = Settings(anthropic_api_key=None)
    assert s.anthropic_api_key is None


def test_user_settings_defaults_when_missing(tmp_path):
    values = load_user_settings(tmp_path)
    assert values == {
        "default_template": "slate",
        "default_depth": "standard",
        "page_size": "Letter",
    }
    assert values == DEFAULT_USER_SETTINGS
    assert values is not DEFAULT_USER_SETTINGS  # must be a copy


def test_user_settings_round_trip(tmp_path):
    saved = save_user_settings(tmp_path, {"default_template": "terminal", "page_size": "A4"})
    assert saved["default_template"] == "terminal"
    assert saved["page_size"] == "A4"
    assert saved["default_depth"] == "standard"
    assert (tmp_path / "settings.json").exists()
    loaded = load_user_settings(tmp_path)
    assert loaded == saved


def test_save_ignores_unknown_keys(tmp_path):
    saved = save_user_settings(tmp_path, {"default_depth": "deep", "bogus": 1})
    assert "bogus" not in saved
    assert saved["default_depth"] == "deep"
