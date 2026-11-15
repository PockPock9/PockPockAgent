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


LEGACY_DATA_DIR_NAME = "FrogAI"


def migrate_legacy_data(app_name: str = "PockPock", legacy_name: str = LEGACY_DATA_DIR_NAME) -> list[str]:
    """Move data from the folder used before the rename (FrogAI) into ``app_name``, once.

    Only entries missing from the new folder are moved, so nothing is overwritten. Entries that
    cannot be moved (for example a log file held open by a service that is still running) stay
    where they are and are tried again next time. Returns the names that were moved.
    """
    legacy = app_data_dir(legacy_name)
    target = app_data_dir(app_name)
    if not legacy.is_dir():
        return []
    target.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for entry in sorted(legacy.iterdir()):
        destination = target / entry.name
        if destination.exists():
            continue
        try:
            entry.rename(destination)
            moved.append(entry.name)
        except OSError:
            continue
    try:
        legacy.rmdir()  # only succeeds when everything was moved
    except OSError:
        pass
    return moved
