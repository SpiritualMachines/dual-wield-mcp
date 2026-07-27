import os
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_SCREENSHOT_DIR = Path.home() / ".local" / "share" / "dual-wield-mcp" / "screenshots"


@dataclass
class ServerConfig:
    screenshot_dir: Path = _DEFAULT_SCREENSHOT_DIR
    spectacle_path: str = "spectacle"
    ydotool_path: str = "ydotool"
    kdotool_path: str = "kdotool"
    wlrctl_path: str = "wlrctl"
    kscreen_doctor_path: str = "kscreen-doctor"
    wl_copy_path: str = "wl-copy"
    wl_paste_path: str = "wl-paste"
    tesseract_path: str = "tesseract"
    window_backend: str = "auto"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> ServerConfig:
        screenshot_dir = Path(
            os.getenv("DUAL_WIELD_SCREENSHOT_DIR", str(_DEFAULT_SCREENSHOT_DIR))
        ).expanduser()
        spectacle_path = os.getenv("DUAL_WIELD_SPECTACLE_PATH", "spectacle")
        ydotool_path = os.getenv("DUAL_WIELD_YDOTOOL_PATH", "ydotool")
        kdotool_path = os.getenv("DUAL_WIELD_KDOTOOL_PATH", "kdotool")
        wlrctl_path = os.getenv("DUAL_WIELD_WLRCTL_PATH", "wlrctl")
        kscreen_doctor_path = os.getenv("DUAL_WIELD_KSCREEN_DOCTOR_PATH", "kscreen-doctor")
        wl_copy_path = os.getenv("DUAL_WIELD_WL_COPY_PATH", "wl-copy")
        wl_paste_path = os.getenv("DUAL_WIELD_WL_PASTE_PATH", "wl-paste")
        tesseract_path = os.getenv("DUAL_WIELD_TESSERACT_PATH", "tesseract")
        window_backend = os.getenv("DUAL_WIELD_WINDOW_BACKEND", "auto")
        log_level = os.getenv("DUAL_WIELD_LOG_LEVEL", "INFO")

        screenshot_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            screenshot_dir=screenshot_dir,
            spectacle_path=spectacle_path,
            ydotool_path=ydotool_path,
            kdotool_path=kdotool_path,
            wlrctl_path=wlrctl_path,
            kscreen_doctor_path=kscreen_doctor_path,
            wl_copy_path=wl_copy_path,
            wl_paste_path=wl_paste_path,
            tesseract_path=tesseract_path,
            window_backend=window_backend,
            log_level=log_level,
        )
