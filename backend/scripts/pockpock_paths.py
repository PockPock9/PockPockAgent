"""Platform-aware locations for PockPock's local user data."""

import os
import sys
from pathlib import Path


def user_data_root() -> Path:
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        return Path(local_app_data).expanduser() if local_app_data else Path.home() / "AppData" / "Local"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        candidate = Path(xdg_data_home).expanduser()
        if candidate.is_absolute():
            return candidate
    return Path.home() / ".local" / "share"


def app_data_dir(app_name: str) -> Path:
    return user_data_root() / app_name
