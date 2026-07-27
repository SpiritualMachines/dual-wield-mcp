from dual_wield_mcp.config import _DEFAULT_SCREENSHOT_DIR, ServerConfig


def test_from_env_returns_defaults(monkeypatch):
    for var in (
        "DUAL_WIELD_SCREENSHOT_DIR",
        "DUAL_WIELD_SPECTACLE_PATH",
        "DUAL_WIELD_LOG_LEVEL",
    ):
        monkeypatch.delenv(var, raising=False)

    config = ServerConfig.from_env()

    assert config.screenshot_dir == _DEFAULT_SCREENSHOT_DIR
    assert config.spectacle_path == "spectacle"
    assert config.log_level == "INFO"


def test_from_env_picks_up_overrides(monkeypatch, tmp_path):
    custom_dir = tmp_path / "custom_screenshots"

    monkeypatch.setenv("DUAL_WIELD_SCREENSHOT_DIR", str(custom_dir))
    monkeypatch.setenv("DUAL_WIELD_SPECTACLE_PATH", "/usr/local/bin/spectacle")
    monkeypatch.setenv("DUAL_WIELD_LOG_LEVEL", "DEBUG")

    config = ServerConfig.from_env()

    assert config.screenshot_dir == custom_dir
    assert custom_dir.is_dir()
    assert config.spectacle_path == "/usr/local/bin/spectacle"
    assert config.log_level == "DEBUG"
